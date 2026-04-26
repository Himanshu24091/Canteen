import os

filepath = r"c:\Users\himan\Desktop\Canteen\templates\groups\activity_feed.html"
with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

replacements = {
    "ðŸ’³": "💳",
    "â€“": "–",
    "â€™": "’",
}

for k, v in replacements.items():
    text = text.replace(k, v)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(text)
print("File fixed.")
