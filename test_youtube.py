 
from app_control import control_app
import time

# Open YouTube search for hi nanna song
result = control_app("chrome_new_tab", {
    "url": "https://www.youtube.com/results?search_query=hi+nanna+song"
})
print(result)