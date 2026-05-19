import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()
key = os.getenv('GROQ_API_KEY')
print(f"Key found: {key[:10]}..." if key else "NO KEY FOUND - .env not loading")

client = Groq(api_key=key)
chat = client.chat.completions.create(
    messages=[{'role': 'user', 'content': 'say hello'}],
    model='llama-3.3-70b-versatile',
)
print(chat.choices[0].message.content)