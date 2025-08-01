#!/usr/bin/env python3
"""
parse_recipe_page.py
--------------------
Extracts recipes from a scanned cookbook page (PNG) and saves them as JSON-LD in .html files.
Also generates a menu image for each recipe using OpenAI's gpt-image-1 model.

Can be imported and called as a function, or run as a CLI.
"""

import argparse, os, base64, json, textwrap, re, openai
from pathlib import Path
from PIL import Image
import requests

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

def generate_menu_image_prompt(recipe_name, recipe_desc, recipe_ingredients, recipe_instructions):
    """
    Create an AI image prompt for a recipe website—realistic, appetizing, with only the prepared food.
    No text, no inedible parts, everything as it would be served after following the recipe.
    """
    # Convert ingredients to a nicely formatted string
    ingredients_str = ", ".join(recipe_ingredients) if recipe_ingredients else ""
    instructions_str = " ".join(
        step if isinstance(step, str) else step.get("text", "")
        for step in (recipe_instructions or [])
    )

    prompt = (
        f"High-quality, realistic photograph of the completed dish '{recipe_name}', "
        f"as it would appear freshly prepared and ready to serve in a professional recipe website photo. "
        f"{recipe_desc.strip() + ' ' if recipe_desc else ''}"
        f"Show only the finished dish, attractively plated, isolated on a neutral background. "
        f"All visible food should be fully prepared, cooked, and presented exactly as described in the recipe, "
        f"with edible garnishes only—no text, no labels, no packaging, no kitchen tools, no hands, no inedible parts. "
        f"For example, fruit should be sliced and hulled as needed, meat should be cooked, and no raw leaves or stems. "
        f"Include only items from these ingredients: {ingredients_str}. "
        f"Present the food in a way that matches the steps: {instructions_str}. "
        f"Do not include any unrelated objects, backgrounds, or people. "
        f"The focus should be entirely on the finished, edible dish, as it would be served."
    )
    return prompt


def generate_menu_image(recipe_name, recipe_desc, recipe_ingredients, recipe_instructions, output_path, api_key):
    """
    Generate an image of the recipe using OpenAI's gpt-image-1 model.
    Saves either by downloading from a URL or decoding base64.
    """
    import base64
    import requests
    from pathlib import Path
    import openai

    client = openai.OpenAI(api_key=api_key)

    prompt = generate_menu_image_prompt(recipe_name, recipe_desc, recipe_ingredients, recipe_instructions)

    prompt_path = Path(str(output_path).replace(".png", ".prompt.txt"))
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"✓ Prompt saved to {prompt_path}")

    try:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            n=1,
            size="1024x1024",
            quality="high"
        )
        data = response.data[0]
        if getattr(data, "url", None):
            img_bytes = requests.get(data.url).content
        elif getattr(data, "b64_json", None):
            img_bytes = base64.b64decode(data.b64_json)
        else:
            print(f"Image generation failed for {recipe_name}: No URL or base64 data returned.")
            return
        with open(output_path, "wb") as f:
            f.write(img_bytes)
        print(f"✓ Image saved to {output_path}")
    except Exception as e:
        print(f"Image generation failed for {recipe_name}: {e}")

def gpt4o_parse_image(image_path: str, api_key: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    client = openai.OpenAI(api_key=api_key)

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

def process_recipe_image(png_path, out_dir, api_key):
    """
    Parse a scanned cookbook page and write out one .html (and .png image) per recipe.
    """
    Path(out_dir).mkdir(exist_ok=True)

    raw_text = gpt4o_parse_image(png_path, api_key)

    if raw_text.lower() == "<no recipe>":
        print(f"[{png_path}] – no recipe detected.")
        return

    # Split raw_text into separate <script type="application/ld+json">...</script> blocks
    scripts = re.findall(
        r'(<script type="application/ld\+json">.*?</script>)',
        raw_text,
        re.DOTALL | re.IGNORECASE
    )
    if not scripts:
        print(f"[{png_path}] – no recipe scripts found.")
        return

    for script in scripts:
        # Extract the JSON content from the <script> tag
        json_match = re.search(
            r'<script[^>]*>(.*?)</script>',
            script,
            re.DOTALL | re.IGNORECASE
        )
        if not json_match:
            print("Warning: Could not extract JSON-LD from script.")
            continue
        json_ld_str = json_match.group(1).strip()

        # Parse JSON-LD to dictionary
        try:
            recipe_data = json.loads(json_ld_str)
        except Exception as e:
            print(f"Error parsing JSON-LD: {e}")
            continue

        # Extract name and slug
        name = recipe_data.get("name", Path(png_path).stem)
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        out_html = Path(out_dir) / f"{slug}.html"
        with open(out_html, "w", encoding="utf-8") as fp:
            fp.write(script.strip() + "\n")
        print(f"✓ Saved {out_html}")

        # Extract description, ingredients, instructions for image generation
        desc = recipe_data.get("description", "")
        ingredients = recipe_data.get("recipeIngredient", [])
        instructions = []
        for step in recipe_data.get("recipeInstructions", []):
            if isinstance(step, dict):
                instructions.append(step.get("text", ""))
            elif isinstance(step, str):
                instructions.append(step)
        img_path = Path(out_dir) / f"{slug}.png"
        generate_menu_image(name, desc, ingredients, instructions, img_path, api_key)

def main():
    ap = argparse.ArgumentParser(
        description="Parse one scanned cookbook PNG into recipe text file(s) using OpenAI Vision"
    )
    ap.add_argument("png", help="Path to the scanned cookbook page (PNG)")
    ap.add_argument("--out-dir", default="recipes_parsed",
                    help="Folder to write recipe .html and .png files")
    ap.add_argument("--api-key", default=None,
                    help="OpenAI API key (or set OPENAI_API_KEY environment variable)")
    args = ap.parse_args()
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        ap.error("You must provide --api-key or set OPENAI_API_KEY in the environment.")
    process_recipe_image(args.png, args.out_dir, api_key)

if __name__ == "__main__":
    main()
