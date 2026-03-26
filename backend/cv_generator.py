import logging
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

CV_GENERATOR_PROMPT = """
You are an expert professional resume writer and career coach.

You have been given:
1. The original resume of a candidate
2. A Job Description (JD) they are targeting
3. An analysis report showing gaps, missing skills, and improvement suggestions

Your task is to generate a completely rewritten, optimized resume/CV tailored to this specific JD.

---

ORIGINAL RESUME:
{resume_text}

---

TARGET JOB DESCRIPTION:
{jd_text}

---

ANALYSIS RESULTS:
- Missing Skills: {missing_skills}
- Present Skills: {present_skills}
- Suggested Improvements: {improvements}
- Optimized Bullet Points: {optimized_bullets}
- Negative Points: {negative_points}

---

INSTRUCTIONS:
1. Keep ALL real experiences, education, and projects from the original resume — do NOT fabricate anything
2. Rewrite bullet points to be more impactful using STAR method (Situation, Task, Action, Result)
3. Add quantifiable metrics where appropriate (improve "managed a team" → "managed a team of 8 engineers, delivering 3 projects ahead of schedule")
4. Incorporate the missing skills ONLY in the Skills section (since the user should learn/add them)
5. Reorder sections to highlight the most relevant experience first
6. Use strong action verbs: Led, Developed, Architected, Optimized, Implemented, Spearheaded
7. Add a tailored Professional Summary at the top
8. Make it ATS-friendly with relevant keywords from the JD
9. Format using clean markdown structure

OUTPUT FORMAT — Generate the resume in clean Markdown:

# [Candidate Name]

**[Email] | [Phone] | [Location] | [LinkedIn/Portfolio]**

---

## Professional Summary
[2-3 sentences tailored to the JD]

---

## Technical Skills
[Categorized skills including relevant ones from JD]

---

## Professional Experience

### [Job Title] | [Company] | [Dates]
- [Impact-driven bullet point with metrics]
- [Another bullet point]

---

## Projects
### [Project Name]
- [Description with technologies and impact]

---

## Education
### [Degree] | [University] | [Year]

---

## Certifications (if applicable)
- [Certification name]

---

RULES:
- Do NOT invent experiences, companies, or degrees
- DO rewrite every bullet point to be stronger and more relevant
- DO add missing JD skills to the Skills section (labeled as "Familiar" or "Learning" if not in original resume)
- DO reorder sections for maximum impact
- Keep it concise — aim for a 1-2 page resume
- Output ONLY the markdown resume, no explanations before or after
"""


def get_cv_llm():
    """Initialize LLM for CV generation — higher token limit."""
    return ChatOllama(
        model="qwen2.5:7b",
        temperature=0.3,
        num_predict=8192,
        num_ctx=8192,
        max_tokens=8192,
        timeout=600.0,
    )


def build_cv_chain():
    """Build the LangChain chain for CV generation."""
    llm = get_cv_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert resume writer. Generate a professional, ATS-optimized resume in clean Markdown format. Output ONLY the resume markdown."),
        ("human", CV_GENERATOR_PROMPT),
    ])
    chain = prompt | llm
    return chain


async def generate_cv(jd_text: str, resume_text: str, analysis_results: dict) -> str:
    """Generate an optimized CV based on analysis results."""
    logger.info("Starting CV generation...")

    # Extract data from analysis for the prompt
    resume_analysis = analysis_results.get("resume_analysis", {})
    improvements = analysis_results.get("improvements", {})
    negative_points = analysis_results.get("negative_points", [])
    optimized_bullets = analysis_results.get("optimized_bullets", [])

    missing_skills = ", ".join(resume_analysis.get("missing_skills", [])[:20]) or "None identified"
    present_skills = ", ".join(resume_analysis.get("present_skills", [])[:20]) or "None identified"

    improvements_text = "\n".join([
        f"Skills to add: {', '.join(improvements.get('skills_to_add', []))}",
        f"Projects to add: {', '.join(improvements.get('projects_to_add', []))}",
        f"Resume tips: {', '.join(improvements.get('resume_tips', []))}",
    ])

    bullets_text = "\n".join([f"- {b}" for b in optimized_bullets[:10]]) or "None"

    negatives_text = "\n".join([
        f"- [{p.get('severity', 'moderate')}] {p.get('issue', '')} → Fix: {p.get('recommendation', '')}"
        for p in negative_points[:10]
    ]) or "None"

    chain = build_cv_chain()

    response = await chain.ainvoke({
        "jd_text": jd_text,
        "resume_text": resume_text,
        "missing_skills": missing_skills,
        "present_skills": present_skills,
        "improvements": improvements_text,
        "optimized_bullets": bullets_text,
        "negative_points": negatives_text,
    })

    logger.info(f"CV generated, length: {len(response.content)} chars")
    return response.content
