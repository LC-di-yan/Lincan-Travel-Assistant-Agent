/** 文案要完整才可替代原始结果；连接中断、格式错误均回退。 */
export async function readNarration(response: Response): Promise<string | null> {
  const reader = response.body?.getReader()
  if (!reader) return null
  const decoder = new TextDecoder()
  let buffer = '', event = '', text = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) return null
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) {
          if (event === 'error') return null
          const data = JSON.parse(line.slice(5))
          if (event === 'done') return text.trim() || null
          if (event === 'delta') {
            if (typeof data.text !== 'string') return null
            text += data.text
          }
          event = ''
        }
      }
    }
  } catch {
    return null
  } finally {
    reader.releaseLock()
  }
}
