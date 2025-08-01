#!/usr/bin/env python3
"""
parse_recipe_page.py
--------------------
Usage:
    python parse_recipe_page.py page_011.png --out-dir parsed_recipes

• Reads a single PNG scan.
• Uses OpenAI Vision (GPT-4o) to extract zero / one / many recipes.
• Writes each extracted recipe to its own .txt file.
"""

import argparse, os, base64, json, textwrap, re, openai
from pathlib import Path
from PIL import Image

# ---------- Prompt sent to GPT-4o ----------
SYSTEM_PROMPT = """
You are a cookbook digitization assistant for importing recipes into Mealie.
You will be sent a scanned cookbook page (a PNG). The page may contain:
  • zero recipes (e.g., TOC, dedication, photo page)
  • one complete recipe
  • multiple recipes

Your job:
1. Carefully analyze the image and, for each recipe present, output a single block in valid JSON-LD format, inside a <script type="application/ld+json"> ... </script> tag. Use the Recipe specification from https://schema.org/Recipe.
2. Fill out these fields if possible:
   - @context, @type, name, author, description, datePublished, prepTime, cookTime, totalTime, recipeYield, keywords, image, recipeIngredient, recipeInstructions
   - Use "@type": "Recipe" for each, and "@type": "HowToStep" for each step in recipeInstructions.
   - For "keywords", always include "My Sisters' Kitchen" first, then one of these valid section keywords as the second (choose the best fit based on the recipe):
        "Appetizers", "Soups", "Salads", "Beverages", "Side Dishes", "Entrees", "Baked Goods", "Desserts", "Other"
   - For "image", use the recipe file name as in the output (see below), e.g.: "https://tidalwave.online/samba1/quick_share/recipes/apple_walnut_cranberry_salad.png"
   - If you cannot determine a value, leave it out rather than guessing, except for times or yields, where you may estimate a reasonable value if typical for that recipe type.

3. Try to capture every step of the instructions as a separate HowToStep. List each ingredient on its own line.

4. For **each recipe**, output a file with this naming style:
   - Lowercase, spaces and punctuation replaced with underscores, ".html" extension (e.g. "apple_walnut_cranberry_salad.html").
   - The contents of each file should be the <script type="application/ld+json">...</script> block for that recipe, and nothing else.

5. If there is more than one recipe on the page, output multiple files (one per recipe), with their correct filenames and contents as above.

6. If there is NO recipe content on the page, respond with exactly: <no recipe>
Do NOT return Markdown, JSON arrays, commentary, or separators – only output the plain text files as specified, or <no recipe>.

7. Do NOT use Markdown formatting, code fences, or language labels. Output only the contents of the HTML file, starting with <script type=...>, nothing else.

8. Name each file using the recipe name, all lowercase, spaces and punctuation replaced with underscores, and the .html extension.
"""


# ---------- OpenAI API call (Vision) ----------
def gpt4o_parse_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    client = openai.OpenAI()  # Uses OPENAI_API_KEY from env

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{b64}",
                            "detail": "high"
                        }
                    }
                ]
            }
        ],
        max_tokens=2048,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()

# ---------- Main CLI ----------
def main():
    ap = argparse.ArgumentParser(
        description="Parse one scanned cookbook PNG into recipe text file(s) "
                    "using OpenAI Vision"
    )
    ap.add_argument("png", help="Path to the scanned cookbook page (PNG)")
    ap.add_argument("--out-dir", default="recipes_parsed",
                    help="Folder to write .txt recipe files")
    args = ap.parse_args()

    Path(args.out_dir).mkdir(exist_ok=True)

    raw_text = gpt4o_parse_image(args.png)

    if raw_text.lower() == "<no recipe>":
        print(f"[{args.png}] – no recipe detected.")
        return

    # Split raw_text into separate <script type="application/ld+json">...</script> blocks
    scripts = re.findall(r'(<script type="application/ld\+json">.*?</script>)', raw_text, re.DOTALL | re.IGNORECASE)
    if not scripts:
        print(f"[{args.png}] – no recipe scripts found.")
        return
    for script in scripts:
        # Extract "name" for filename
        m = re.search(r'"name"\s*:\s*"([^"]+)"', script)
        if m:
            name = m.group(1)
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        else:
            slug = Path(args.png).stem
        out_path = Path(args.out_dir) / f"{slug}.html"
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(script.strip() + "\n")
        print(f"✓ Saved {out_path}")

if __name__ == "__main__":
    main()

