import json
import re
import logging
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from prompt_template import RESUME_ANALYZER_PROMPT
from semantic_matcher import SemanticMatcher

logger = logging.getLogger(__name__)

# Initialize semantic matcher (loads model once)
matcher = SemanticMatcher()


def get_llm():
    """Initialize the Ollama LLM with Qwen 2.5."""
    return ChatOllama(
        model="qwen2.5:7b",
        temperature=0.1,
        num_predict=8192,
        num_ctx=8192,
        max_tokens=8192,
        format="json",
        timeout=600.0,
    )


def build_chain():
    """Build the LangChain analysis chain."""
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert resume analyzer. You MUST respond with ONLY valid JSON. No explanations, no markdown, just the JSON object."),
        ("human", RESUME_ANALYZER_PROMPT),
    ])
    chain = prompt | llm
    return chain


def extract_json(text: str) -> dict:
    """Extract JSON from LLM response, handling markdown code blocks and repairs."""
    logger.info(f"Raw LLM response (first 500 chars): {text[:500]}")
    logger.info(f"Raw LLM response length: {len(text)}")

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try finding JSON object boundaries
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        json_str = text[start:end + 1]
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Repair: fix missing commas between key-value pairs
        # Pattern: "value"\n\n  "key" → "value",\n\n  "key"
        repaired = re.sub(r'"\s*\n(\s*)"', r'",\n\1"', json_str)
        # Pattern: ]\n  "key" → ],\n  "key"
        repaired = re.sub(r'\]\s*\n(\s*)"', r'],\n\1"', repaired)
        # Pattern: }\n  "key" → },\n  "key"
        repaired = re.sub(r'\}\s*\n(\s*)"', r'},\n\1"', repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            logger.error(f"Repaired JSON still failed: {e}")

    # Last resort: try to fix truncated JSON by closing brackets
    if start != -1:
        json_str = text[start:]
        # Count open/close brackets
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')

        # Try to close truncated JSON
        # First, fix any trailing incomplete string
        json_str = re.sub(r',\s*$', '', json_str)  # remove trailing comma
        json_str = re.sub(r'"[^"]*$', '""', json_str)  # close incomplete string

        # Add missing closing brackets
        json_str += ']' * (open_brackets - close_brackets)
        json_str += '}' * (open_braces - close_braces)

        # Also repair commas
        json_str = re.sub(r'"\s*\n(\s*)"', r'",\n\1"', json_str)
        json_str = re.sub(r'\]\s*\n(\s*)"', r'],\n\1"', json_str)
        json_str = re.sub(r'\}\s*\n(\s*)"', r'},\n\1"', json_str)

        try:
            result = json.loads(json_str)
            logger.warning("Parsed truncated/repaired JSON successfully")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Truncation repair failed: {e}")

    raise ValueError(f"Could not extract valid JSON from LLM response. Response starts with: {text[:200]}")


async def analyze_resume(jd_text: str, resume_text: str) -> dict:
    """
    Hybrid analysis pipeline:
    1. Semantic similarity via all-MiniLM-L6-v2 + ChromaDB
    2. LLM analysis via Qwen 2.5 (enriched with similarity data)
    3. Merge results
    """

    # ---- Step 1: Semantic Similarity ----
    logger.info("Step 1: Computing semantic similarity...")
    semantic_results = matcher.compute_similarity(jd_text, resume_text)

    overall_sim = semantic_results["overall_similarity"]
    skill_sim = semantic_results["skill_similarity"]
    matched = semantic_results["matched_skills"]
    missing = semantic_results["missing_skills"]

    logger.info(f"Semantic similarity: overall={overall_sim:.3f}, skill={skill_sim:.3f}")
    logger.info(f"Matched skills: {len(matched)}, Missing skills: {len(missing)}")

    # Build a context string from semantic results to feed into the LLM
    semantic_context = f"""
--- SEMANTIC ANALYSIS RESULTS (pre-computed via embedding similarity) ---
Overall Cosine Similarity: {overall_sim:.2%}
Skill Match Rate: {skill_sim:.2%}

Matched Skills (from embeddings):
{chr(10).join(f'  - {m["jd_skill"]} → {m["resume_skill"]} (sim: {m["similarity"]})' for m in matched[:15])}

Missing Skills (not found in resume):
{chr(10).join(f'  - {s}' for s in missing[:15])}

JD Skills Detected: {', '.join(semantic_results['jd_skills_found'][:20])}
Resume Skills Detected: {', '.join(semantic_results['resume_skills_found'][:20])}
--- END SEMANTIC ANALYSIS ---
"""

    # ---- Step 2: LLM Analysis (enriched with semantic data) ----
    logger.info("Step 2: Invoking LLM chain with semantic context...")
    chain = build_chain()

    # Append semantic context to the JD text so the LLM can use it
    enriched_jd = jd_text + "\n\n" + semantic_context

    response = await chain.ainvoke({
        "jd_text": enriched_jd,
        "resume_text": resume_text,
    })

    logger.info(f"LLM response length: {len(response.content)}")

    result = extract_json(response.content)
    logger.info(f"Parsed JSON keys: {list(result.keys())}")

    # ---- Step 3: Merge & Enhance ----
    # Inject semantic similarity data into the result
    result["semantic_similarity"] = {
        "overall": round(overall_sim * 100, 1),
        "skill_match": round(skill_sim * 100, 1),
        "matched_skills_count": len(matched),
        "missing_skills_count": len(missing),
    }

    # Use semantic data to calibrate the match score if LLM score seems off
    llm_score = result.get("match_score", 0)
    semantic_score = round(overall_sim * 100)

    # Weighted blend: 60% LLM score + 40% semantic score
    blended_score = round(0.6 * llm_score + 0.4 * semantic_score)
    result["match_score"] = blended_score
    result["score_breakdown"] = {
        "llm_score": llm_score,
        "semantic_score": semantic_score,
        "blended_score": blended_score,
    }

    # Ensure missing_skills in resume_analysis reflects semantic findings
    if "resume_analysis" in result:
        existing_missing = set(result["resume_analysis"].get("missing_skills", []))
        for skill in missing:
            existing_missing.add(skill)
        result["resume_analysis"]["missing_skills"] = list(existing_missing)

    # Add top section matches for transparency
    result["top_section_matches"] = semantic_results.get("top_section_matches", [])

    # Ensure all required keys exist with defaults
    defaults = {
        "match_score": 0,
        "summary": "",
        "jd_analysis": {
            "required_skills": [],
            "tools_technologies": [],
            "experience_level": "",
            "responsibilities": []
        },
        "resume_analysis": {
            "present_skills": [],
            "missing_skills": [],
            "partial_matches": [],
            "irrelevant_sections": []
        },
        "gap_analysis": [],
        "negative_points": [],
        "improvements": {
            "skills_to_add": [],
            "projects_to_add": [],
            "keywords_to_add": [],
            "resume_tips": []
        },
        "optimized_bullets": [],
        "template_suggestions": {
            "recommended_format": "modern",
            "reason": ""
        }
    }

    for key, default_val in defaults.items():
        if key not in result:
            result[key] = default_val
        elif isinstance(default_val, dict):
            for sub_key, sub_default in default_val.items():
                if sub_key not in result[key]:
                    result[key][sub_key] = sub_default

    logger.info(f"Final blended score: {blended_score} (LLM: {llm_score}, Semantic: {semantic_score})")
    return result
