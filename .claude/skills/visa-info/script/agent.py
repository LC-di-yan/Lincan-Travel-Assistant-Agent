"""
签证信息智能体 VisaInfoAgent
职责：基于向量数据库的签证知识检索与问答

复用 RAG 管线（Milvus Lite + sentence-transformers），独立 collection。
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict
import json
import logging
import os
import hashlib
from pathlib import Path

from utils.llm_response import extract_llm_text
from cache.decorators import cached

# gRPC keepalive
_GRPC_KEEPALIVE_MS = '600000'
os.environ['GRPC_KEEPALIVE_TIME_MS'] = _GRPC_KEEPALIVE_MS
os.environ['GRPC_KEEPALIVE_TIMEOUT_MS'] = '20000'
os.environ['GRPC_KEEPALIVE_PERMIT_WITHOUT_CALLS'] = '0'
os.environ['GRPC_HTTP2_MIN_RECV_PING_INTERVAL_WITHOUT_DATA_MS'] = _GRPC_KEEPALIVE_MS
os.environ['GRPC_HTTP2_MIN_PING_INTERVAL_WITHOUT_DATA_MS'] = _GRPC_KEEPALIVE_MS

logger = logging.getLogger(__name__)

try:
    from pymilvus import MilvusClient
    from sentence_transformers import SentenceTransformer
    DEPENDENCIES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"RAG dependencies not available: {e}")
    DEPENDENCIES_AVAILABLE = False

# Embedding model singleton cache
_EMBEDDING_MODEL_CACHE: Dict[str, 'SentenceTransformer'] = {}

def _get_embedding_model(model_path: str) -> 'SentenceTransformer':
    if model_path not in _EMBEDDING_MODEL_CACHE:
        logger.info(f"Loading embedding model: {model_path}")
        _EMBEDDING_MODEL_CACHE[model_path] = SentenceTransformer(model_path, local_files_only=True)
    return _EMBEDDING_MODEL_CACHE[model_path]

# Result cache
_VISA_CACHE: Dict[str, Dict] = {}
_CACHE_MAX_SIZE = 50


class VisaInfoAgent(AgentBase):
    """签证信息智能体"""

    def __init__(
        self,
        name: str = "VisaInfoAgent",
        model=None,
        collection_name: str = "visa_knowledge",
        top_k: int = 3,
        **kwargs
    ):
        super().__init__()
        self.name = name
        self.model = model
        self.collection_name = collection_name
        self.top_k = top_k

        if not DEPENDENCIES_AVAILABLE:
            logger.error("RAG dependencies not installed")
            self.initialized = False
            return

        # Load embedding model
        try:
            from config import RAG_CONFIG
            embedding_model = RAG_CONFIG.get("embedding_model", "BAAI/bge-small-zh-v1.5")
        except Exception:
            embedding_model = "BAAI/bge-small-zh-v1.5"

        model_path = Path(embedding_model).expanduser()
        if not model_path.is_absolute():
            model_path = Path.cwd() / model_path
        if model_path.exists():
            model_path_or_id = str(model_path.resolve())
        else:
            model_path_or_id = "BAAI/bge-small-zh-v1.5"

        self.embedding_model = _get_embedding_model(model_path_or_id)
        self.embedding_dim = self.embedding_model.get_sentence_embedding_dimension()

        # Init Milvus Lite
        milvus_db_dir = Path.home() / ".aligo" / "milvus_data"
        milvus_db_dir.mkdir(parents=True, exist_ok=True)
        milvus_db_path = str(milvus_db_dir / "milvus_lite.db")

        self.milvus_client = MilvusClient(milvus_db_path)
        self._milvus_db_path = milvus_db_path

        if self.milvus_client.has_collection(collection_name):
            logger.info(f"Loaded existing visa collection: {collection_name}")
            try:
                self.milvus_client.load_collection(collection_name)
            except Exception:
                pass
        else:
            logger.info(f"Creating new visa collection: {collection_name}")
            self.milvus_client.create_collection(
                collection_name=collection_name,
                dimension=self.embedding_dim,
                metric_type="COSINE",
                auto_id=False,
            )

        self.initialized = True
        logger.info("VisaInfoAgent initialized successfully")

    def add_documents(self, documents: List[Dict[str, str]]) -> Dict:
        """添加签证文档到知识库"""
        if not self.initialized:
            return {"status": "error", "message": "Agent not initialized"}

        try:
            stats = self.milvus_client.get_collection_stats(self.collection_name)
            current_count = stats.get("row_count", 0)

            data_to_insert = []
            for i, doc in enumerate(documents):
                doc_id = current_count + i + 1
                content = doc['content']
                metadata = doc.get('metadata', {})
                embedding = self.embedding_model.encode(content).tolist()
                data_to_insert.append({
                    "id": doc_id,
                    "vector": embedding,
                    "content": content,
                    "metadata": json.dumps(metadata, ensure_ascii=False)
                })

            self.milvus_client.insert(
                collection_name=self.collection_name,
                data=data_to_insert
            )

            stats = self.milvus_client.get_collection_stats(self.collection_name)
            return {
                "status": "success",
                "added_count": len(documents),
                "total_count": stats.get("row_count", 0)
            }
        except Exception as e:
            logger.error(f"Error adding visa documents: {e}")
            return {"status": "error", "message": str(e)}

    def search_knowledge(self, query: str, top_k: Optional[int] = None) -> List[Dict]:
        """检索签证知识库"""
        if not self.initialized:
            return []

        try:
            k = top_k or self.top_k
            query_embedding = self.embedding_model.encode(query).tolist()

            results = self.milvus_client.search(
                collection_name=self.collection_name,
                data=[query_embedding],
                limit=k,
                output_fields=["id", "content", "metadata"]
            )

            retrieved_docs = []
            if results and len(results) > 0:
                for hit in results[0]:
                    metadata_str = hit.get("entity", {}).get("metadata", "{}")
                    try:
                        metadata = json.loads(metadata_str)
                    except Exception:
                        metadata = {}

                    retrieved_docs.append({
                        'id': hit.get("entity", {}).get("id", ""),
                        'content': hit.get("entity", {}).get("content", ""),
                        'metadata': metadata,
                        'distance': hit.get("distance", 0.0)
                    })

            return retrieved_docs
        except Exception as e:
            logger.error(f"Error searching visa knowledge: {e}")
            return []

    @cached("visa_info", ttl=21600)
    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        """签证问答主流程"""
        if not self.initialized:
            return Msg(name=self.name, content=json.dumps({
                "status": "error",
                "message": "VisaInfoAgent not initialized"
            }), role="assistant")

        if x is None:
            return Msg(name=self.name, content=json.dumps({}), role="assistant")

        # Extract query
        if isinstance(x, list):
            content = x[-1].content if x else ""
        else:
            content = x.content

        user_query = content
        if isinstance(content, str) and content.strip().startswith('{'):
            try:
                data = json.loads(content)
                if "context" in data and isinstance(data["context"], dict):
                    user_query = data["context"].get("rewritten_query", "") or content
                elif "rewritten_query" in data:
                    user_query = data.get("rewritten_query", "") or content
            except Exception:
                pass

        # Check cache
        cache_key = hashlib.md5(user_query.encode()).hexdigest()
        if cache_key in _VISA_CACHE:
            cached = _VISA_CACHE[cache_key]
            return Msg(name=self.name, content=json.dumps(cached, ensure_ascii=False), role="assistant")

        # Search
        retrieved_docs = self.search_knowledge(user_query)

        if not retrieved_docs:
            result = {
                "status": "no_knowledge",
                "query": user_query,
                "answer": "抱歉，签证知识库中没有找到相关信息。建议查阅目的地国家的大使馆官网获取最新签证政策。",
                "retrieved_documents": []
            }
            return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

        # Build context
        knowledge_context = "\n\n".join([
            f"【签证信息{i+1}】\n{doc['content']}"
            for i, doc in enumerate(retrieved_docs)
        ])

        if self.model:
            prompt = f"""基于以下签证知识库信息回答用户问题，简洁准确，不超过500字。

【问题】{user_query}

【签证知识库】
{knowledge_context}

【约束】
1. 只基于知识库信息回答，没有就直接说"签证知识库中没有找到相关信息"
2. 不要编造答案
3. 提醒用户签证政策可能随时变化，建议出行前确认最新信息
4. 额外输出"proactive_question"字段：用"需要我帮你..."开头自然延伸一句反问（25字内），如不需要则设为""
"""

            try:
                messages = [
                    {"role": "system", "content": "你是签证咨询专家，简洁回答。提醒用户政策可能变化。"},
                    {"role": "user", "content": prompt}
                ]
                response = await self.model(messages)
                answer = extract_llm_text(response, fallback="无法生成答案")
                if not answer:
                    answer = "无法生成答案"
            except Exception as e:
                logger.error(f"Error generating visa answer: {e}")
                answer = f"签证知识库中找到相关信息，但生成答案时出错：{str(e)}"
        else:
            answer = "以下是签证知识库中的相关信息：\n\n" + knowledge_context

        result = {
            "status": "success",
            "query": user_query,
            "answer": answer,
            "proactive_question": "需要我帮你了解其他国家的签证政策吗？",
            "retrieved_documents": [
                {
                    "content": doc['content'][:200] + "..." if len(doc['content']) > 200 else doc['content'],
                    "metadata": doc['metadata']
                }
                for doc in retrieved_docs
            ]
        }

        # Cache
        if len(_VISA_CACHE) >= _CACHE_MAX_SIZE:
            keys_to_remove = list(_VISA_CACHE.keys())[:_CACHE_MAX_SIZE // 2]
            for k in keys_to_remove:
                del _VISA_CACHE[k]
        _VISA_CACHE[cache_key] = result

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
