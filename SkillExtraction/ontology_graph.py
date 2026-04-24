"""
Skill ontology graph building module
Build Job-Skill-RelatedRole graph structure from job-skill association table
and export to JSON (nodes/links) directly usable by D3.js
"""

import json
import logging
from typing import Dict, Optional, List

import psycopg2

from config import DB_CONFIG, MERGED_JOBS_TABLE, NORMALIZED_JOB_SKILLS_TABLE

logger = logging.getLogger(__name__)


class SkillOntologyBuilder:
    """
    Build "job-skill-related role" ontology graph from normalized_job_skills table
    """

    def __init__(self, db_config: Dict = None):
        self.db_config = db_config or DB_CONFIG

    def construct_skill_ontology_graph(
        self,
        job_table: str = MERGED_JOBS_TABLE,
        job_id_column: str = "job_id",
        title_column: str = "title",
        limit_jobs: Optional[int] = 500,
        similarity_threshold: float = 0.3,
    ) -> Dict:
        """
        Build a "job-skill-related role" ontology graph.

        The graph carries three node/edge types:
        - Job node:     (job_id, title)
        - Skill node:   normalized skill name
        - Related-role edge: two jobs with highly overlapping skill sets.

        The return value is a plain Python dict ready for ``json.dumps`` and
        downstream consumers (e.g. D3.js visualisations).
        """
        try:
            conn = psycopg2.connect(**self.db_config)
            cursor = conn.cursor()

            logger.info("=" * 80)
            logger.info("Start building skill ontology graph (Job-Skill-Role Ontology)")
            logger.info("=" * 80)

            # 1) Select job IDs that have appeared in normalized_job_skills
            job_id_query = f"""
                SELECT DISTINCT job_id
                FROM {NORMALIZED_JOB_SKILLS_TABLE}
                WHERE job_id IS NOT NULL AND job_id <> ''
            """
            if limit_jobs:
                job_id_query += " LIMIT %s"
                cursor.execute(job_id_query, (limit_jobs,))
            else:
                cursor.execute(job_id_query)

            job_ids_raw = cursor.fetchall()
            job_ids = [row[0] for row in job_ids_raw]

            if not job_ids:
                logger.warning("No job data in normalized_job_skills, cannot build ontology graph")
                cursor.close()
                conn.close()
                return {
                    "jobs": [],
                    "skills": [],
                    "edges": {"job_skill": [], "related_roles": []},
                }

            logger.info(f"Number of jobs participating in graph construction: {len(job_ids)}")

            # 2) Read the titles of these jobs
            # Note: Here we assume that job_table.{job_id_column} can correspond to normalized_job_skills.job_id
            job_ids_param = tuple(job_ids)
            job_placeholders = ",".join(["%s"] * len(job_ids))
            cursor.execute(
                f"""
                SELECT {job_id_column}, {title_column}
                FROM {job_table}
                WHERE {job_id_column}::text IN ({job_placeholders})
                """,
                job_ids_param,
            )

            job_meta_rows = cursor.fetchall()
            job_meta: Dict[str, Dict] = {}
            for row in job_meta_rows:
                jid = str(row[0])
                title = row[1] if row[1] is not None else ""
                job_meta[jid] = {
                    "id": f"job:{jid}",
                    "job_id": jid,
                    "title": str(title),
                    "type": "job",
                }

            # 3) Read job-skill association (normalized skills)
            cursor.execute(
                f"""
                SELECT job_id, normalized_skill_name
                FROM {NORMALIZED_JOB_SKILLS_TABLE}
                WHERE job_id = ANY(%s)
                  AND normalized_skill_name IS NOT NULL
                  AND normalized_skill_name <> ''
                """,
                (job_ids,),
            )

            rows = cursor.fetchall()

            cursor.close()
            conn.close()

            # 4) Construct nodes and Job-Skill edges
            job_skills: Dict[str, set] = {}
            skill_nodes: Dict[str, Dict] = {}
            job_skill_edges: List[Dict] = []

            for job_id_raw, skill_name in rows:
                job_id = str(job_id_raw)
                if job_id not in job_meta:
                    # There may be records in normalized_job_skills, but not in the given job_table
                    continue

                skill_key = (skill_name or "").strip()
                if not skill_key:
                    continue

                # Record job -> skills set
                job_skills.setdefault(job_id, set()).add(skill_key)

                # Skill node
                if skill_key not in skill_nodes:
                    skill_nodes[skill_key] = {
                        "id": f"skill:{skill_key}",
                        "name": skill_key,
                        "type": "skill",
                    }

                # Job-Skill edge
                job_skill_edges.append(
                    {
                        "source": job_meta[job_id]["id"],
                        "target": skill_nodes[skill_key]["id"],
                        "type": "has_skill",
                        "weight": 1.0,
                    }
                )

            logger.info(
                "Number of job nodes: %d, number of skill nodes: %d, number of Job-Skill edges: %d",
                len(job_meta),
                len(skill_nodes),
                len(job_skill_edges),
            )

            # 5) Calculate job similarity based on skill sets, generate "related role" edges
            related_role_edges: List[Dict] = []
            job_ids_for_sim = list(job_skills.keys())
            n_jobs_sim = len(job_ids_for_sim)

            logger.info(
                "Start calculating job skill similarity for 'related role' inference, total number of jobs: %d",
                n_jobs_sim,
            )

            for i in range(n_jobs_sim):
                jid_i = job_ids_for_sim[i]
                skills_i = job_skills[jid_i]
                if not skills_i:
                    continue

                for j in range(i + 1, n_jobs_sim):
                    jid_j = job_ids_for_sim[j]
                    skills_j = job_skills[jid_j]
                    if not skills_j:
                        continue

                    # Jaccard similarity
                    inter = len(skills_i & skills_j)
                    if inter == 0:
                        continue

                    union = len(skills_i | skills_j)
                    sim = inter / union if union > 0 else 0.0

                    if sim >= similarity_threshold:
                        related_role_edges.append(
                            {
                                "source": job_meta[jid_i]["id"],
                                "target": job_meta[jid_j]["id"],
                                "type": "related_role",
                                "weight": float(sim),
                            }
                        )

            logger.info(
                "Number of related role edges: %d (threshold=%.3f)",
                len(related_role_edges),
                similarity_threshold,
            )

            graph = {
                "jobs": list(job_meta.values()),
                "skills": list(skill_nodes.values()),
                "edges": {
                    "job_skill": job_skill_edges,
                    "related_roles": related_role_edges,
                },
            }

            logger.info("Skill ontology graph construction completed")
            logger.info("=" * 80)

            return graph

        except Exception as e:
            logger.error(f"Failed to build skill ontology graph: {e}")
            return {
                "jobs": [],
                "skills": [],
                "edges": {"job_skill": [], "related_roles": []},
            }

    @staticmethod
    def to_d3_format(graph: Dict) -> Dict:
        """
        Convert internal graph format to D3.js common format: {nodes:[], links:[]}
        - nodes: job + skill nodes
        - links: has_skill + related_role edges
        """
        nodes: List[Dict] = []
        links: List[Dict] = []

        nodes.extend(graph.get("jobs", []))
        nodes.extend(graph.get("skills", []))

        for e in graph.get("edges", {}).get("job_skill", []):
            links.append(
                {
                    "source": e["source"],
                    "target": e["target"],
                    "type": e.get("type", "has_skill"),
                    "weight": float(e.get("weight", 1.0)),
                }
            )

        for e in graph.get("edges", {}).get("related_roles", []):
            links.append(
                {
                    "source": e["source"],
                    "target": e["target"],
                    "type": e.get("type", "related_role"),
                    "weight": float(e.get("weight", 0.0)),
                }
            )

        return {"nodes": nodes, "links": links}

    @staticmethod
    def save_json(data: Dict, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    """
    Command line entry:
    Run this file directly, it will build an example skill ontology graph and export JSON files:
    - skill_ontology_graph.json (original format)
    - skill_ontology_d3.json (D3 nodes/links format)
    """
    logging.basicConfig(level=logging.INFO)

    builder = SkillOntologyBuilder()

    # Defaults follow the configured MERGED_JOBS_TABLE; override via environment
    # variable MERGED_JOBS_TABLE if you want to build from a different snapshot.
    job_table = MERGED_JOBS_TABLE
    job_id_column = "job_id"
    title_column = "title"

    graph = builder.construct_skill_ontology_graph(
        job_table=job_table,
        job_id_column=job_id_column,
        title_column=title_column,
        limit_jobs=20,
        similarity_threshold=0.3,
    )

    jobs_cnt = len(graph.get("jobs", []))
    skills_cnt = len(graph.get("skills", []))
    job_skill_edges_cnt = len(graph.get("edges", {}).get("job_skill", []))
    related_roles_edges_cnt = len(graph.get("edges", {}).get("related_roles", []))

    logger.info("=" * 80)
    logger.info("Ontology graph statistics (ontology_graph.py directly run)")
    logger.info("=" * 80)
    logger.info(f"Number of job nodes: {jobs_cnt}")
    logger.info(f"Number of skill nodes: {skills_cnt}")
    logger.info(f"Number of Job-Skill edges: {job_skill_edges_cnt}")
    logger.info(f"Number of related role edges: {related_roles_edges_cnt}")
    logger.info("=" * 80)

    # Export: original graph
    builder.save_json(graph, "skill_ontology_graph.json")
    logger.info("Exported: skill_ontology_graph.json")

    # Export: D3 format
    d3_graph = builder.to_d3_format(graph)
    builder.save_json(d3_graph, "skill_ontology_d3.json")
    logger.info("Exported: skill_ontology_d3.json (D3 nodes/links)")

    logger.info("If you want to view in the browser, please run: python -m http.server 8001")
    logger.info("Then open: http://localhost:8001 (with your D3 index.html)")


if __name__ == "__main__":
    main()