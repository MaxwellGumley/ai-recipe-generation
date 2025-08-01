#!/usr/bin/env python3
"""
parse_recipe_page.py
--------------------
Extracts recipes from a scanned cookbook page (PNG) and saves them as JSON‑LD in .html files.
Also generates a menu image for each recipe using OpenAI’s gpt‑image‑1 model.

Can be imported and called as a function, or run as a CLI.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from pathlib import Path

import openai
import requests

# ────────────────────────────────────────────────────────────────────────────────
# Where the PNGs will live once they’re copied to your web‑server.
# Change this in ONE place if the hosting path ever moves.
# Keep the trailing slash for convenience.
# ────────────────────────────────────────────────────────────────────────────────
BASE_IMAGE_URL = "https://tidalwave.online/samba1/quick_share/recipes/"
# ────────────────────────────────────────────────────────────────────────────────


# ---------- Prompt sent to GPT‑4o ------------------------------------------------
SYSTEM_PROMPT = f"""
You are a cookbook digitization assistant for importing recipes into Mealie.
You will be sent a scanned cookbook page (a PNG). The page may contain:
  • zero recipes (e.g., TOC, dedication, photo page)
  • one complete recipe
  • multiple recipes

Your job:
1. Carefully analyze the image and, for each recipe present, output a single block in valid JSON‑LD format, inside a <script type="application/ld+json"> … </script> tag. Use the Recipe specification from https://schema.org/Recipe.
2. Fill out these fields if possible:
   - @context, @type, name, author, description, datePublished, prepTime, cookTime, totalTime, recipeYield, keywords, image, recipeIngredient, recipeInstructions
   - Use "@type": "Recipe" for each, and "@type": "HowToStep" for each step in recipeInstructions.
   - For "keywords", always include "My Sisters' Kitchen" first, then one of these valid section keywords as the second (choose the best fit based on the recipe):
        "Appetizers", "Soups", "Salads", "Beverages", "Side Dishes", "Entrees", "Baked Goods", "Desserts", "Other"
   - For "image", build the URL like this: "{BASE_IMAGE_URL}<slug>.png" where <slug> is the kebab‑style file name you will output.
   - If you cannot determine a value, leave it out rather than guessing, except for times or yields, where you may estimate a reasonable value if typical for that recipe type.

3. Try to capture every step of the instructions as a separate HowToStep. List each ingredient on its own line.

4. For **each recipe**, output a file with this naming style:
   - Lowercase, spaces and punctuation replaced with underscores, ".html" extension (e.g. "apple_walnut_cranberry_salad.html").
   - The contents of each file should be the <script type="application/ld+json">…</script> block for that recipe, and nothing else.

5. If there is more than one recipe on the page, output multiple files (one per recipe), with their correct filenames and contents as above.

6. If there is NO recipe content on the page, respond with exactly: <no recipe>
Do NOT return Markdown, JSON arrays, commentary, or separators – only output the plain text files as specified, or <no recipe>.

7. Do NOT use Markdown formatting, code fences, or language labels. Output only the contents of the HTML file, starting with <script type=…>, nothing else.

8. Name each file using the recipe name, all lowercase, spaces and punctuation replaced with underscores, and the .html extension.
"""

# ────────────────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────────────────

def generate_menu_image_prompt(
    recipe_name: str,
    recipe_desc: str,
    recipe_ingredients: list[str],
    recipe_instructions: list[str | dict[str, str]],
) -> str:
    """Craft an image‑generation prompt for the finished dish."""

    ingredients_str = ", ".join(recipe_ingredients) if recipe_ingredients else ""
    instructions_str = " ".join(
        step if isinstance(step, str) else step.get("text", "")
        for step in (recipe_instructions or [])
    )

    return (
        f"High‑quality, realistic photograph of the completed dish '{recipe_name}', "
        f"as it would appear freshly prepared and ready to serve in a professional recipe website photo. "
        f"{recipe_desc.strip() + ' ' if recipe_desc else ''}"
        f"Show only the finished dish, attractively plated, isolated on a neutral background. "
        f"All visible food should be fully prepared, cooked, and presented exactly as described in the recipe, "
        f"with edible garnishes only—no text, no labels, no packaging, no kitchen tools, no hands, no inedible parts. "
        f"Include only items from these ingredients: {ingredients_str}. "
        f"Present the food in a way that matches the steps: {instructions_str}. "
        f"The focus should be entirely on the finished, edible dish, as it would be served."
    )


def generate_menu_image(
    recipe_name: str,
    recipe_desc: str,
    recipe_ingredients: list[str],
    recipe_instructions: list[str | dict[str, str]],
    output_path: Path,
    api_key: str,
) -> None:
    """Generate the hero image for a recipe using OpenAI’s Images API."""

    client = openai.OpenAI(api_key=api_key)

    prompt = generate_menu_image_prompt(
        recipe_name, recipe_desc, recipe_ingredients, recipe_instructions
    )

    prompt_path = output_path.with_suffix(".prompt.txt")
    prompt_path.write_text(prompt, encoding="utf‑8")
    print(f"✓ Prompt saved to {prompt_path}")

    try:
        response = client.images.generate(
            model="gpt-image-1",
            prompt=prompt,
            n=1,
            size="1024x1024",
            quality="high",
        )
        data = response.data[0]
        if getattr(data, "url", None):
            img_bytes = requests.get(data.url).content
        elif getattr(data, "b64_json", None):
            img_bytes = base64.b64decode(data.b64_json)
        else:
            print(f"Image generation failed for {recipe_name}: No data returned.")
            return

        output_path.write_bytes(img_bytes)
        print(f"✓ Image saved to {output_path}")
    except Exception as exc:
        print(f"Image generation failed for {recipe_name}: {exc}")


def gpt4o_parse_image(image_path: Path, api_key: str) -> str:
    """Send the PNG to GPT‑4o and return its raw response text."""

    b64 = base64.b64encode(image_path.read_bytes()).decode()
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
                            "detail": "high",
                        },
                    }
                ],
            },
        ],
        max_tokens=2048,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()


# ────────────────────────────────────────────────────────────────────────────────
# Core processing
# ────────────────────────────────────────────────────────────────────────────────

def process_recipe_image(
    png_path: str | Path,
    out_dir: str | Path,
    api_key: str,
) -> None:
    """Parse one scanned page and emit HTML + PNG files for each recipe found."""

    png_path = Path(png_path).expanduser().resolve()
    out_dir = Path(out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_text = gpt4o_parse_image(png_path, api_key)
    if raw_text.lower() == "<no recipe>":
        print(f"[{png_path}] – no recipe detected.")
        return

    # Extract every <script …>…</script> block
    scripts = re.findall(
        r"(<script type=\"application/ld\+json\">.*?</script>)",
        raw_text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not scripts:
        print(f"[{png_path}] – no recipe scripts found.")
        return

    for script_block in scripts:
        # Pull the JSON text out of the <script> tag
        m = re.search(
            r"<script[^>]*>(.*?)</script>", script_block, flags=re.DOTALL | re.IGNORECASE
        )
        if not m:
            print("Warning: could not extract JSON‑LD block.")
            continue

        try:
            recipe_data = json.loads(m.group(1).strip())
        except Exception as err:
            print(f"Error parsing JSON‑LD: {err}")
            continue

        name = recipe_data.get("name", png_path.stem)
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

        # Build and inject the image URL
        recipe_data["image"] = f"{BASE_IMAGE_URL}{slug}.png"

        # Re‑serialize the fixed JSON‑LD
        script_fixed = (
            "<script type=\"application/ld+json\">\n"
            + json.dumps(recipe_data, ensure_ascii=False, indent=2)
            + "\n</script>"
        )

        out_html = out_dir / f"{slug}.html"
        out_html.write_text(script_fixed + "\n", encoding="utf‑8")
        print(f"✓ Saved {out_html}")

        # Generate hero image
        desc = recipe_data.get("description", "")
        ingredients = recipe_data.get("recipeIngredient", [])
        instructions = [
            step.get("text", "") if isinstance(step, dict) else step
            for step in recipe_data.get("recipeInstructions", [])
        ]
        img_path = out_dir / f"{slug}.png"
        generate_menu_image(name, desc, ingredients, instructions, img_path, api_key)


# ────────────────────────────────────────────────────────────────────────────────
# CLI wrapper
# ────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse one scanned cookbook PNG into recipe file(s) and hero image"
    )
    parser.add_argument("png", help="Path to the scanned cookbook page (PNG)")
    parser.add_argument(
        "--out-dir",
        default="recipes_parsed",
        help="Folder to write recipe .html and .png files",
    )
    parser.add_argument(
        "--api-key",
        help="OpenAI API key (falls back to OPENAI_API_KEY env var)",
    )

    args = parser.parse_args()
    api_key = args.api_key or os.getenv("OPENAI_API_KEY")
    if not api_key:
        parser.error("You must provide --api-key or set OPENAI_API_KEY in the environment.")

    process_recipe_image(args.png, args.out_dir, api_key)


if __name__ == "__main__":
    main()
