"""
LLM-based reasoning for job recommendations.
Provides deterministic fallbacks when no LLM credentials are configured.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional
from urllib import error, request

from user_profile import UserProfile

logger = logging.getLogger(__name__)


class RecommendationReasoner:
    """Generate recommendation explanations and identify skill gaps."""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or self._default_config()
        self.last_error: Optional[str] = None
        self._load_env_file()

    def _default_config(self) -> Dict:
        return {
            "enabled": True,
            "use_llm": False,
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": None,
            "api_key_env": "DEEPSEEK_API_KEY",
            "env_file": ".env",
            "http_proxy": None,
            "https_proxy": None,
            "timeout_seconds": 20,
            "max_skill_gaps": 5,
            "max_learning_suggestions": 3,
            "log_errors": True,
        }

    def enrich_ranked_jobs(self, user_profile: UserProfile, ranked_jobs: List[Dict]) -> List[Dict]:
        """Attach reasoning payload to ranked jobs."""
        enriched_jobs = []
        for job_info in ranked_jobs:
            enriched = dict(job_info)
            enriched["reasoning"] = self.generate_reasoning(user_profile, job_info)
            enriched_jobs.append(enriched)
        return enriched_jobs

    def generate_reasoning(self, user_profile: UserProfile, job_info: Dict) -> Dict:
        """Generate reasoning, optionally using an LLM."""
        context = self._build_context(user_profile, job_info)
        fallback = self._build_fallback_reasoning(context)
        self.last_error = None

        if not self.config.get("enabled", True):
            return self._fallback_with_reason(fallback, "LLM reasoning is disabled.")

        if not self.config.get("use_llm"):
            return self._fallback_with_reason(fallback, "LLM calling is turned off in config.")

        api_key = self._resolve_api_key()
        if not api_key:
            return self._fallback_with_reason(
                fallback,
                "No API key found. Configure `api_key`, set the env var, or provide a `.env` file.",
            )

        llm_reasoning = self._call_llm(context, api_key)
        if not llm_reasoning:
            return self._fallback_with_reason(fallback, self.last_error or "Unknown LLM error.")

        return self._merge_reasoning(fallback, llm_reasoning)

    def _load_env_file(self) -> None:
        """Load variables from a local .env file when present."""
        env_file = self.config.get("env_file")
        if not env_file:
            return

        env_path = env_file
        if not os.path.isabs(env_path):
            env_path = os.path.abspath(env_path)

        if not os.path.exists(env_path):
            return

        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'").strip('"')
                    os.environ.setdefault(key, value)
        except OSError as exc:
            self._log_error(f"Failed to read env file `{env_path}`: {exc}")

    def _resolve_api_key(self) -> Optional[str]:
        """Resolve API key from config, env var, or loaded .env file."""
        direct_key = self.config.get("api_key")
        if direct_key:
            return str(direct_key)

        env_name = self.config.get("api_key_env", "OPENAI_API_KEY")
        return os.getenv(env_name)

    def _fallback_with_reason(self, fallback: Dict, reason: str) -> Dict:
        """Attach fallback metadata and emit a visible log message."""
        self.last_error = reason
        self._log_error(f"Using fallback reasoning: {reason}")
        enriched = dict(fallback)
        enriched["fallback_reason"] = reason
        return enriched

    def _log_error(self, message: str) -> None:
        """Log LLM errors when enabled."""
        if self.config.get("log_errors", True):
            logger.warning(message)

    def _build_context(self, user_profile: UserProfile, job_info: Dict) -> Dict:
        job = job_info["job"]
        details = job_info.get("details", {})
        description = job.get("description") or ""
        requirements = job.get("requirements") or ""

        user_skills = {skill.name.lower(): skill for skill in user_profile.skills}
        required_skills = [skill for skill in job.get("required_skills", []) if skill]
        preferred_skills = [skill for skill in job.get("preferred_skills", []) if skill]

        matched_skills = []
        missing_required_skills = []
        weak_skills = []

        for skill_name in required_skills:
            normalized = skill_name.lower()
            user_skill = user_skills.get(normalized)
            if not user_skill:
                missing_required_skills.append(skill_name)
                continue

            matched_skills.append(skill_name)
            if user_skill.proficiency < 0.65 or user_skill.years_of_experience < 1:
                weak_skills.append(
                    {
                        "skill": skill_name,
                        "proficiency": round(user_skill.proficiency, 2),
                        "years_of_experience": round(user_skill.years_of_experience, 1),
                    }
                )

        matched_preferred_skills = [
            skill for skill in preferred_skills if skill.lower() in user_skills
        ]

        highest_education = user_profile.get_highest_education()
        return {
            "job": {
                "job_id": job.get("job_id"),
                "title": job.get("title", "Unknown Title"),
                "company": job.get("company", "Unknown Company"),
                "location": job.get("location", "Unknown Location"),
                "industry": job.get("industry", "Unknown"),
                "required_skills": required_skills,
                "preferred_skills": preferred_skills,
                "education_requirement": job.get("education_requirement", "Unknown"),
                "experience_years": job.get("experience_years", 0),
                "description": description[:1200],
                "requirements": requirements[:1200],
            },
            "user": {
                "name": user_profile.name,
                "skills": [skill.name for skill in user_profile.skills],
                "education": highest_education.level.value if highest_education else "Unknown",
                "major": highest_education.major if highest_education else "Unknown",
                "experience_years": round(user_profile.get_total_experience_years(), 1),
                "preferred_locations": user_profile.constraints.locations,
                "preferred_industries": user_profile.constraints.industries,
            },
            "scores": {
                "match_score": round(job_info.get("match_score", 0), 4),
                "final_score": round(job_info.get("final_score", 0), 4),
                "relevance": round(job_info.get("relevance", 0), 4),
                "feasibility": round(job_info.get("feasibility", 0), 4),
                "growth": round(job_info.get("growth", 0), 4),
                "skill_score": round(details.get("skill_score", 0), 4),
                "education_score": round(details.get("education_score", 0), 4),
                "experience_score": round(details.get("experience_score", 0), 4),
                "location_score": round(details.get("location_score", 0), 4),
            },
            "analysis": {
                "matched_skills": matched_skills,
                "matched_preferred_skills": matched_preferred_skills,
                "missing_required_skills": missing_required_skills,
                "weak_skills": weak_skills,
            },
        }

    def _build_fallback_reasoning(self, context: Dict) -> Dict:
        analysis = context["analysis"]
        scores = context["scores"]

        strengths = []
        if analysis["matched_skills"]:
            strengths.append(
                "Covered core skills: " + ", ".join(analysis["matched_skills"][:3])
            )
        if analysis["matched_preferred_skills"]:
            strengths.append(
                "Matched preferred skills: " + ", ".join(analysis["matched_preferred_skills"][:2])
            )
        if scores["education_score"] >= 0.9:
            strengths.append("Education background is well aligned with the job requirements.")
        if scores["location_score"] >= 0.8:
            strengths.append("Job location matches the user's preference.")

        skill_gaps = []
        for skill_name in analysis["missing_required_skills"][: self.config["max_skill_gaps"]]:
            skill_gaps.append(
                {
                    "skill": skill_name,
                    "importance": "high",
                    "status": "missing",
                    "reason": "This skill appears in the job requirements but is not reflected in the user profile.",
                }
            )

        remaining_slots = max(0, self.config["max_skill_gaps"] - len(skill_gaps))
        for weak_skill in analysis["weak_skills"][:remaining_slots]:
            skill_gaps.append(
                {
                    "skill": weak_skill["skill"],
                    "importance": "medium",
                    "status": "needs_improvement",
                    "reason": (
                        f"The user has some background, but proficiency is {weak_skill['proficiency']:.0%} "
                        f"with {weak_skill['years_of_experience']} years of experience, so improvement is still needed."
                    ),
                }
            )

        learning_suggestions = [
            (
                f"Build `{gap['skill']}`: set a 4–8 week goal (course, small project, or work sample) tied to this job's "
                f"requirements, then reassess fit."
            )
            for gap in skill_gaps[: self.config["max_learning_suggestions"]]
        ]
        if not learning_suggestions:
            learning_suggestions.append(
                "Your profile is close on explicit skills; deepen domain projects and document outcomes to strengthen readiness."
            )

        # Single narrative: readiness + gaps + pathway (strengths stay in the `strengths` array for optional UI, not repeated here)
        reasoning_parts = [
            f"Overall fit is about {scores['final_score']:.0%} (relevance {scores['relevance']:.0%}). "
            "Use that as a rough readiness signal alongside your own review of the full posting."
        ]
        if skill_gaps:
            reasoning_parts.append(
                " Concrete gaps to address: "
                + ", ".join(gap["skill"] for gap in skill_gaps[:4])
                + ". Closing these will materially improve alignment."
            )
        else:
            reasoning_parts.append(
                " Against the skills we can see, you largely meet requirements; focus next on depth, proof of impact, and any niche tools the employer stresses."
            )
        reasoning_parts.append(
            " Plan development in short milestones (courses, certifications, or scoped projects) rather than vague study goals."
        )

        return {
            "source": "fallback",
            "recommendation_reasoning": "".join(reasoning_parts),
            "strengths": strengths,
            "matched_skills": analysis["matched_skills"],
            "skill_gaps": skill_gaps,
            "learning_suggestions": learning_suggestions,
        }

    def _call_llm(self, context: Dict, api_key: str) -> Optional[Dict]:
        prompt = self._build_prompt(context)
        payload = {
            "model": self.config["model"],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a career coach assistant. Your job is to help users assess their readiness for a role, "
                        "identify concrete skill gaps with evidence from the input, and suggest realistic development "
                        "pathways (courses, practice, or experience) — not generic praise. "
                        "Return strict JSON only. Do not invent skills, employers, or facts not supported by the input. "
                        "Write in English only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }

        base_url = self.config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        endpoint = f"{base_url}/chat/completions"
        req = request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        proxy_config = {}
        http_proxy = self.config.get("http_proxy") or os.getenv("HTTP_PROXY")
        https_proxy = self.config.get("https_proxy") or os.getenv("HTTPS_PROXY")
        if http_proxy:
            proxy_config["http"] = http_proxy
        if https_proxy:
            proxy_config["https"] = https_proxy

        opener = request.build_opener(request.ProxyHandler(proxy_config))

        try:
            with opener.open(req, timeout=self.config["timeout_seconds"]) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                error_body = exc.read().decode("utf-8")[:1000]
            except Exception:
                error_body = ""
            self.last_error = f"HTTP {exc.code} from LLM API. {error_body}".strip()
            self._log_error(self.last_error)
            return None
        except error.URLError as exc:
            self.last_error = f"Network error while calling LLM API: {exc}"
            self._log_error(self.last_error)
            return None
        except TimeoutError as exc:
            self.last_error = f"LLM request timed out: {exc}"
            self._log_error(self.last_error)
            return None
        except json.JSONDecodeError as exc:
            self.last_error = f"Failed to decode LLM HTTP response: {exc}"
            self._log_error(self.last_error)
            return None

        try:
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raw_content = body.get("choices", [{}])
            self.last_error = f"Failed to parse LLM JSON payload: {exc}. Raw response: {str(raw_content)[:1000]}"
            self._log_error(self.last_error)
            return None

        return self._normalize_llm_output(parsed)

    def _build_prompt(self, context: Dict) -> str:
        return (
            "Analyze this job against the user profile. Answer in English only.\n\n"
            "Focus the narrative on: (1) readiness for this role given scores and skills, "
            "(2) concrete skill gaps with brief evidence from the data, "
            "(3) realistic career development pathways (what to learn or build next and on what timeline).\n"
            "Avoid repeating the same idea in recommendation_reasoning and in strengths: use "
            "`recommendation_reasoning` for the integrated coaching paragraph; use `strengths` for at most "
            "3 short bullet-style lines that add non-redundant positives (or [] if everything is already in the paragraph).\n\n"
            "Return a JSON object with exactly these keys:\n"
            "recommendation_reasoning: string (one cohesive paragraph, no bullet list inside)\n"
            "strengths: array of strings (0–3 items, optional; must not duplicate the main paragraph)\n"
            "skill_gaps: array of objects with keys skill, importance, status, reason\n"
            "learning_suggestions: array of strings (actionable steps toward the role)\n\n"
            "Context:\n"
            f"{json.dumps(context, ensure_ascii=False, indent=2)}"
        )

    def _normalize_llm_output(self, payload: Dict) -> Dict:
        skill_gaps = []
        for item in payload.get("skill_gaps", []):
            if not isinstance(item, dict):
                continue
            skill_name = item.get("skill")
            if not skill_name:
                continue
            skill_gaps.append(
                {
                    "skill": str(skill_name),
                    "importance": str(item.get("importance", "medium")),
                    "status": str(item.get("status", "missing")),
                    "reason": str(item.get("reason", "")),
                }
            )

        return {
            "source": "llm",
            "recommendation_reasoning": str(payload.get("recommendation_reasoning", "")),
            "strengths": [str(item) for item in payload.get("strengths", []) if str(item).strip()],
            "matched_skills": [],
            "skill_gaps": skill_gaps,
            "learning_suggestions": [
                str(item)
                for item in payload.get("learning_suggestions", [])
                if str(item).strip()
            ],
        }

    def _merge_reasoning(self, fallback: Dict, llm_reasoning: Dict) -> Dict:
        merged = dict(fallback)
        merged["source"] = llm_reasoning.get("source", "llm")
        merged["recommendation_reasoning"] = (
            llm_reasoning.get("recommendation_reasoning")
            or fallback["recommendation_reasoning"]
        )
        merged["strengths"] = llm_reasoning.get("strengths") or fallback["strengths"]
        merged["skill_gaps"] = llm_reasoning.get("skill_gaps") or fallback["skill_gaps"]
        merged["learning_suggestions"] = (
            llm_reasoning.get("learning_suggestions")
            or fallback["learning_suggestions"]
        )
        if not llm_reasoning.get("matched_skills"):
            merged["matched_skills"] = fallback["matched_skills"]
        else:
            merged["matched_skills"] = llm_reasoning["matched_skills"]
        return merged
