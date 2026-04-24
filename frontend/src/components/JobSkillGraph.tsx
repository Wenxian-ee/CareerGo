import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, formatUnknownError } from '@/api/client';

type Node = {
  id: string;
  label: string;
  group: string;
  job_id?: string;
  job_url?: string;
  normalized_skill_name?: string;
};
type Link = { source: string; target: string; weight?: number };

type GraphPayload = {
  nodes: Node[];
  links: Link[];
  empty_reason?: string;
  error?: string;
};

type Positioned = {
  node: Node;
  x: number;
  y: number;
  angle: number; // radians, 0 = right, measured around center
};

const LABEL_GAP = 10; // gap between circle edge and first character of label
const SKILL_MIN_GAP = 80; // minimum arc length between adjacent skill labels
const RELATED_MIN_GAP = 120; // minimum arc length between adjacent related jobs

function labelWidth(label: string, fontSize: number): number {
  const s = label.length > 38 ? 38 : label.length;
  return Math.max(30, Math.round(s * fontSize * 0.55));
}

function truncate(s: string, max = 38): string {
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/**
 * Place nodes on two rings (skills inside, related jobs outside) with radii
 * that grow with label count so labels don't collide.
 */
function layout(nodes: Node[]): { positioned: Positioned[]; rSkill: number; rRel: number } {
  const job = nodes.find((n) => n.group === 'job');
  const skills = nodes.filter((n) => n.group === 'skill');
  const related = nodes.filter((n) => n.group === 'related_job');

  const rSkill = Math.max(110, Math.ceil((SKILL_MIN_GAP * Math.max(skills.length, 1)) / (2 * Math.PI)));
  const rRel = rSkill + Math.max(120, Math.ceil((RELATED_MIN_GAP * Math.max(related.length, 1)) / (2 * Math.PI)));

  const positioned: Positioned[] = [];
  if (job) {
    positioned.push({ node: job, x: 0, y: 0, angle: -Math.PI / 2 });
  }

  // Skills distributed over the full circle, starting from the top.
  skills.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(skills.length, 1) - Math.PI / 2;
    positioned.push({
      node: n,
      x: rSkill * Math.cos(a),
      y: rSkill * Math.sin(a),
      angle: a,
    });
  });

  // Related jobs also distributed over the full circle, offset by half a slot
  // so they don't sit exactly behind a skill label.
  const relOffset = Math.PI / Math.max(related.length, 1);
  related.forEach((n, i) => {
    const a = (2 * Math.PI * i) / Math.max(related.length, 1) - Math.PI / 2 + relOffset;
    positioned.push({
      node: n,
      x: rRel * Math.cos(a),
      y: rRel * Math.sin(a),
      angle: a,
    });
  });

  return { positioned, rSkill, rRel };
}

/** Compute a viewBox that keeps all node labels inside. */
function computeViewBox(pts: Positioned[], pad: number) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of pts) {
    const fontSize = p.node.group === 'job' ? 12 : p.node.group === 'related_job' ? 11 : 10;
    const labelW = labelWidth(truncate(p.node.label), fontSize);
    const rad = radiusFor(p.node.group);
    // Assume label is placed along radial direction outward; bounding box
    // extends by rad + LABEL_GAP + labelW along that ray in the worst case.
    const reach = rad + LABEL_GAP + labelW;
    const dx = Math.cos(p.angle) * reach;
    const dy = Math.sin(p.angle) * reach;
    const nxA = p.x + dx;
    const nyA = p.y + dy;
    const nxB = p.x - dx * 0.2; // small back-side padding
    const nyB = p.y - dy * 0.2;
    minX = Math.min(minX, nxA, nxB, p.x - rad, p.x + rad);
    maxX = Math.max(maxX, nxA, nxB, p.x - rad, p.x + rad);
    minY = Math.min(minY, nyA, nyB, p.y - rad, p.y + rad);
    maxY = Math.max(maxY, nyA, nyB, p.y - rad, p.y + rad);
  }
  if (!Number.isFinite(minX)) {
    return { vx: -220, vy: -160, vw: 440, vh: 320 };
  }
  return {
    vx: minX - pad,
    vy: minY - pad,
    vw: maxX - minX + 2 * pad,
    vh: maxY - minY + 2 * pad,
  };
}

function radiusFor(group: string): number {
  return group === 'job' ? 11 : group === 'related_job' ? 9 : 7;
}

type PanZoom = { tx: number; ty: number; k: number };

const ZOOM_MIN = 0.35;
const ZOOM_MAX = 4;

export function JobSkillGraph({ jobId }: { jobId: string }) {
  const navigate = useNavigate();
  const [data, setData] = useState<GraphPayload | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [useRelatedFallback, setUseRelatedFallback] = useState(false);
  const [pz, setPz] = useState<PanZoom>({ tx: 0, ty: 0, k: 1 });
  const [dragging, setDragging] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{ active: boolean; lastX: number; lastY: number } | null>(null);
  const movedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setErr(null);
    setPz({ tx: 0, ty: 0, k: 1 });
    api
      .getJobSkillGraph(jobId, useRelatedFallback)
      .then((g) => {
        if (!cancelled) setData(g);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErr(formatUnknownError(e));
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, useRelatedFallback]);

  const scene = useMemo(() => {
    if (!data?.nodes?.length) return null;

    const { positioned } = layout(data.nodes);
    const posById = new Map<string, Positioned>(positioned.map((p) => [p.node.id, p]));
    const view = computeViewBox(positioned, 36);

    const stroke = (g: string) =>
      g === 'job' ? 'var(--accent)' : g === 'skill' ? 'var(--accent-mid)' : '#8b7355';
    const fill = (g: string) =>
      g === 'job'
        ? 'var(--accent-soft)'
        : g === 'skill'
          ? 'var(--accent-soft-2)'
          : '#f5efe8';

    // Classify links for distinct visual treatment.
    const lines = data.links.map((l, i) => {
      const a = posById.get(l.source);
      const b = posById.get(l.target);
      if (!a || !b) return null;
      const aG = a.node.group;
      const bG = b.node.group;
      // skill <-> related_job bridge edges are thin + dashed so they read as
      // "this is the reason these two are linked" rather than primary structure.
      const isBridge =
        (aG === 'skill' && bG === 'related_job') ||
        (aG === 'related_job' && bG === 'skill');
      return (
        <line
          key={`e-${i}`}
          x1={a.x}
          y1={a.y}
          x2={b.x}
          y2={b.y}
          stroke={isBridge ? 'rgba(139,115,85,0.45)' : 'rgba(22,24,28,0.22)'}
          strokeDasharray={isBridge ? '3 4' : undefined}
          strokeWidth={isBridge ? 1 : 1 + Math.min((l.weight ?? 1) / 8, 3)}
        />
      );
    });

    const circles = positioned.map((p) => {
      const n = p.node;
      const rad = radiusFor(n.group);
      const jumpJobId = (n.job_id || '').trim();
      const jumpJobUrl = (n.job_url || '').trim();
      const clickable = !!jumpJobId || !!jumpJobUrl;
      const onClick = () => {
        if (movedRef.current) return;
        if (jumpJobUrl) {
          window.open(jumpJobUrl, '_blank', 'noopener,noreferrer');
          return;
        }
        if (!jumpJobId) return;
        navigate(`/jobs/${encodeURIComponent(jumpJobId)}`);
      };

      // Radial label placement: push the label outward along the angle so it
      // never collides with the node glyph or inner ring.
      const fontSize = n.group === 'job' ? 12 : n.group === 'related_job' ? 11 : 10;
      const fontWeight = n.group === 'job' ? 600 : n.group === 'related_job' ? 500 : 400;
      const labelDistance = rad + LABEL_GAP;
      const cosA = Math.cos(p.angle);
      const sinA = Math.sin(p.angle);
      // Center job sits at origin, no meaningful angle -> put its label above.
      const labelX = n.group === 'job' ? p.x : p.x + cosA * labelDistance;
      const labelY = n.group === 'job' ? p.y - rad - LABEL_GAP : p.y + sinA * labelDistance;
      let textAnchor: 'start' | 'middle' | 'end';
      if (n.group === 'job') {
        textAnchor = 'middle';
      } else if (cosA > 0.3) {
        textAnchor = 'start';
      } else if (cosA < -0.3) {
        textAnchor = 'end';
      } else {
        textAnchor = 'middle';
      }
      // For labels near the horizontal axis (|cos| large, |sin| small), shift
      // vertically so the baseline lines up with the node center.
      const dy = Math.abs(cosA) > 0.7 ? '0.32em' : sinA > 0 ? '0.85em' : '-0.25em';

      return (
        <g
          key={n.id}
          onClick={onClick}
          style={{ cursor: clickable ? 'pointer' : 'default' }}
          role={clickable ? 'button' : undefined}
          tabIndex={clickable ? 0 : undefined}
          onKeyDown={
            clickable
              ? (e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onClick();
                  }
                }
              : undefined
          }
        >
          <circle cx={p.x} cy={p.y} r={rad + 3} fill={fill(n.group)} opacity={0.95} />
          <circle cx={p.x} cy={p.y} r={rad} fill="#fff" stroke={stroke(n.group)} strokeWidth={2} />
          <text
            x={labelX}
            y={labelY}
            textAnchor={textAnchor}
            dy={n.group === 'job' ? undefined : dy}
            fontSize={fontSize}
            fill="var(--text)"
            style={{
              fontWeight,
              pointerEvents: 'none',
              paintOrder: 'stroke',
              stroke: 'rgba(255,255,255,0.9)',
              strokeWidth: 3,
            }}
          >
            {truncate(n.label)}
          </text>
        </g>
      );
    });

    return { lines, circles, view };
  }, [data, navigate]);

  const clientToSvg = useCallback((clientX: number, clientY: number) => {
    const el = svgRef.current;
    if (!el) return { x: 0, y: 0 };
    const pt = el.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const ctm = el.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  }, []);

  const applyWheelZoom = useCallback(
    (e: WheelEvent) => {
      e.preventDefault();
      const { x: mx, y: my } = clientToSvg(e.clientX, e.clientY);
      const factor = e.deltaY > 0 ? 0.92 : 1.09;
      setPz((prev) => {
        const k0 = prev.k;
        let k1 = k0 * factor;
        if (k1 < ZOOM_MIN) k1 = ZOOM_MIN;
        if (k1 > ZOOM_MAX) k1 = ZOOM_MAX;
        const ratio = k1 / k0;
        return {
          k: k1,
          tx: mx - (mx - prev.tx) * ratio,
          ty: my - (my - prev.ty) * ratio,
        };
      });
    },
    [clientToSvg],
  );

  useEffect(() => {
    const el = svgRef.current;
    if (!el || !scene) return;
    el.addEventListener('wheel', applyWheelZoom, { passive: false });
    return () => el.removeEventListener('wheel', applyWheelZoom);
  }, [scene, applyWheelZoom]);

  const onPointerDown = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    (e.currentTarget as SVGSVGElement).setPointerCapture(e.pointerId);
    dragRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
    movedRef.current = false;
    setDragging(true);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    const d = dragRef.current;
    if (!d?.active) return;
    const dx = e.clientX - d.lastX;
    const dy = e.clientY - d.lastY;
    if (Math.abs(dx) + Math.abs(dy) > 2) movedRef.current = true;
    d.lastX = e.clientX;
    d.lastY = e.clientY;
    const el = svgRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const vb = el.viewBox.baseVal;
    const sx = (vb.width / rect.width) * dx;
    const sy = (vb.height / rect.height) * dy;
    setPz((prev) => ({ ...prev, tx: prev.tx + sx, ty: prev.ty + sy }));
  }, []);

  const endDrag = useCallback((e: React.PointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.active) {
      try {
        (e.currentTarget as SVGSVGElement).releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    }
    dragRef.current = null;
    setDragging(false);
    setTimeout(() => {
      movedRef.current = false;
    }, 0);
  }, []);

  const resetView = useCallback(() => {
    setPz({ tx: 0, ty: 0, k: 1 });
  }, []);

  if (err) {
    return <p className="muted small">Could not load skill graph: {err}</p>;
  }
  if (!data) {
    return <p className="muted small">Loading skill graph…</p>;
  }
  if (data.error && (!data.nodes?.length || data.nodes.length <= 1)) {
    return <p className="muted small">Skill graph unavailable ({data.error}).</p>;
  }

  let emptyMessage: string | null = null;
  if (data.nodes.length <= 1) {
    emptyMessage =
      data.empty_reason === 'no_skills_for_job'
        ? 'No skill records were found for this job in normalized or raw skill columns yet.'
        : 'No skills for this job are linked to any related role yet, so the graph is empty.';
  }
  return (
    <div className="skill-graph-wrap">
      <div className="skill-graph-toolbar" style={{ justifyContent: 'space-between' }}>
        <label className="muted small" style={{ display: 'inline-flex', gap: '0.4rem', alignItems: 'center' }}>
          <input
            type="checkbox"
            checked={useRelatedFallback}
            onChange={(e) => setUseRelatedFallback(e.target.checked)}
          />
          Enable similar-jobs fallback when skill links are missing
        </label>
      </div>
      {scene ? (
        <svg
          ref={svgRef}
          className="skill-graph-svg"
          viewBox={`${scene.view.vx} ${scene.view.vy} ${scene.view.vw} ${scene.view.vh}`}
          role="img"
          aria-label="Skill graph"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          style={{ touchAction: 'none', cursor: dragging ? 'grabbing' : 'grab' }}
        >
          <title>Job and skill connections</title>
          <g transform={`translate(${pz.tx},${pz.ty}) scale(${pz.k})`}>
            {scene.lines}
            {scene.circles}
          </g>
        </svg>
      ) : (
        <p className="muted small">{emptyMessage}</p>
      )}
      <div className="skill-graph-toolbar">
        <button type="button" className="btn btn-ghost btn-small" onClick={resetView}>
          Reset view
        </button>
        <span className="muted small">Scroll to zoom · Drag to pan</span>
      </div>
      <p className="muted small" style={{ marginTop: '0.35rem' }}>
        Center: this role. Inner ring: skills that also appear in a related role. Outer ring: related
        roles sharing those skills. Dashed lines show which skill links the center to each related role.
        {data.empty_reason === 'fallback_related_only'
          ? ' Showing related jobs fallback because no skill links were found for this job.'
          : ''}
      </p>
    </div>
  );
}
