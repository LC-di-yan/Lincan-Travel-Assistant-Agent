import inspect
from typesafe_sdk import endpoints
src = inspect.getsource(endpoints)
print(src[:3000])
