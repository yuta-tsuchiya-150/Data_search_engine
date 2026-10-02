
import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])

model = genai.GenerativeModel("gemini-3.6-flash")

response = model.generate_content("Hello! Please reply in one word.")
print(response.text)
