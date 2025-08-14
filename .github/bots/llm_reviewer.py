from openai import OpenAI
import os, subprocess, json, requests

# Create OpenAI client with your secret key from GitHub Actions Secrets
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Environment variables set by the workflow
repo = os.environ["REPO"]
pr_number = os.environ["PR_NUMBER"]
base_ref = os.environ["BASE_REF"]
gh_token = os.environ["GITHUB_TOKEN"]

# Step 1: Make sure we have the latest base branch
subprocess.run(["git", "fetch", "origin", base_ref], check=False)

# Step 2: Get the diff for the PR compared to the base branch
diff = subprocess.check_output(
    ["git", "diff", f"origin/{base_ref}", "--unified=0"]
).decode(errors="ignore")

# Step 3: Ask the AI for review suggestions in JSON format
prompt = f"""
You are a strict, helpful code reviewer.
Review the following diff and produce a JSON object with an array 'suggestions'.
Each suggestion must have:
- "filename": file path
- "line": line number in the new file (RIGHT side of diff)
- "comment": a concise suggestion with rationale

Return ONLY valid JSON. Do not include markdown formatting or explanations outside of JSON.

Diff:
{diff}
"""

resp = client.responses.create(
    model="gpt-4o",
    input=[
        {"role": "system", "content": "You are a precise code review assistant."},
        {"role": "user", "content": prompt}
    ],
    response_format={"type": "json_object"}
)

try:
    content = resp.output_text.strip()
    data = json.loads(content)
except Exception as e:
    print("Error parsing AI response:", e)
    data = {"suggestions": []}

# Step 4: Function to post review comments to the PR
def post_comment(suggestion):
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments"
    payload = {
        "body": suggestion["comment"],
        "path": suggestion["filename"],
        "line": int(suggestion["line"]),
        "side": "RIGHT"
    }
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json"
        },
        json=payload
    )
    if r.status_code >= 300:
        print(f"Failed to comment ({r.status_code}): {r.text}")

# Step 5: Loop through suggestions and post them
for s in data.get("suggestions", []):
    try:
        post_comment(s)
    except Exception as e:
        print("Error posting comment:", e)
