"""Pure-Pillow Tech-Tree & Dependency Graph Renderer for dgg-pm.

Generates high-resolution Civilization-style tech trees as PNG buffers directly
usable in Discord messages. Handles layered DAG depth calculation, dummy slot
routing around intermediate nodes, barycenter edge crossing reduction, and
dynamic status theming.
"""

from __future__ import annotations

import io
from itertools import pairwise
from typing import Any

from PIL import Image, ImageDraw, ImageFont

# --- Color Palette & Aesthetics ---
BG_COLOR = "#0b0c0f"
GRID_COLOR = "#14171c"
BANNER_BG_START = "#0c1b29"
BANNER_BG_END = "#0b0c0f"
BORDER_LINE = "#232830"

THEME: dict[str, dict[str, str]] = {
    "complete": {
        "fill": "#12281e",
        "edge": "#31c77a",
        "text": "#e5fff0",
        "accent": "#31c77a",
        "badge_bg": "#1d4731",
        "badge_text": "#4ee396",
    },
    "active": {
        "fill": "#112d45",
        "edge": "#49b7ff",
        "text": "#f4f9ff",
        "accent": "#49b7ff",
        "badge_bg": "#1d4468",
        "badge_text": "#80d0ff",
    },
    "available": {
        "fill": "#10283b",
        "edge": "#1098f7",
        "text": "#f4f9ff",
        "accent": "#1098f7",
        "badge_bg": "#163a56",
        "badge_text": "#54b8ff",
    },
    "locked": {
        "fill": "#17191d",
        "edge": "#343941",
        "text": "#9ba5b5",
        "accent": "#596270",
        "badge_bg": "#252a32",
        "badge_text": "#7a8494",
    },
    "blocked": {
        "fill": "#241416",
        "edge": "#d94848",
        "text": "#ffebeb",
        "accent": "#d94848",
        "badge_bg": "#421c20",
        "badge_text": "#ff8585",
    },
}

LABEL: dict[str, str] = {
    "complete": "COMPLETE",
    "active": "IN PROGRESS",
    "available": "READY TO START",
    "locked": "LOCKED",
    "blocked": "BLOCKED",
}

NODE_W = 300
NODE_H = 175
DUMMY_W = 28
DUMMY_H = 22
H_GAP = 80
V_GAP = 32
MAX_EDGE = 3600
PAD = 44
TITLE_H = 86


def _load_font(bold: bool, size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    names = (
        (
            "DejaVuSans-Bold.ttf",
            "arialbd.ttf",
            "LiberationSans-Bold.ttf",
        )
        if bold
        else (
            "DejaVuSans.ttf",
            "arial.ttf",
            "LiberationSans-Regular.ttf",
        )
    )
    roots = (
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/TTF",
        "/usr/share/fonts/truetype/liberation",
        "C:/Windows/Fonts",
        "/System/Library/Fonts",
        "",
    )
    for root in roots:
        for name in names:
            try:
                return ImageFont.truetype(f"{root}/{name}" if root else name, size)
            except OSError:
                continue
    return ImageFont.load_default()


F_TITLE = _load_font(True, 26)
F_SUBTITLE = _load_font(False, 13)
F_NAME = _load_font(True, 15)
F_SMALL = _load_font(False, 12)
F_TAG = _load_font(True, 10)
F_PILL = _load_font(False, 10)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, max_w: int, max_lines: int = 2) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            if len(lines) >= max_lines:
                break
            cur = w
    if len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and len(lines) < len(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = (last + "…") if last != lines[-1] else lines[-1]
    return lines


# --- Layer Calculation & Routing ---


def compute_layers(nodes: list[dict[str, Any]], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Computes column/layer index for each node using longest path from root in DAG."""
    prereqs: dict[str, list[str]] = {n["key"]: [] for n in nodes}
    for src, dst in edges:
        if dst in prereqs and src in prereqs:
            prereqs[dst].append(src)

    depth: dict[str, int] = {}
    visiting: set[str] = set()

    def walk(k: str) -> int:
        if k in depth:
            return depth[k]
        if k in visiting:  # cycle safeguard
            return 0
        visiting.add(k)
        d = 0 if not prereqs[k] else 1 + max(walk(p) for p in prereqs[k])
        visiting.discard(k)
        depth[k] = d
        return d

    for n in nodes:
        walk(n["key"])
    return depth


def plan_layout(
    nodes: list[dict[str, Any]], edges: list[tuple[str, str]]
) -> tuple[dict[int, list[str]], dict[tuple[str, str], list[str]], dict[str, int]]:
    """Assigns nodes and dummy routing slots to layers and orders them to minimize crossings."""
    depth = compute_layers(nodes, edges)
    layers: dict[int, list[str]] = {}
    for n in nodes:
        layers.setdefault(depth[n["key"]], []).append(n["key"])

    routing: list[tuple[str, str]] = []
    chains: dict[tuple[str, str], list[str]] = {}
    for src, dst in edges:
        if src not in depth or dst not in depth:
            continue
        d0, d1 = depth[src], depth[dst]
        if d1 - d0 <= 1:
            routing.append((src, dst))
            chains[(src, dst)] = []
            continue
        chain: list[str] = []
        prev = src
        for d in range(d0 + 1, d1):
            dk = f"\x00{src}>{dst}@{d}"
            depth[dk] = d
            layers.setdefault(d, []).append(dk)
            routing.append((prev, dk))
            chain.append(dk)
            prev = dk
        routing.append((prev, dst))
        chains[(src, dst)] = chain

    preds: dict[str, list[str]] = {}
    succs: dict[str, list[str]] = {}
    for a, b in routing:
        preds.setdefault(b, []).append(a)
        succs.setdefault(a, []).append(b)

    order = {d: list(ks) for d, ks in layers.items()}
    idx: dict[str, int] = {}

    def reindex() -> None:
        idx.clear()
        for ks in order.values():
            for i, k in enumerate(ks):
                idx[k] = i

    reindex()

    # Barycenter sweeps
    max_d = max(order.keys(), default=0)
    for _ in range(4):
        for d in range(1, max_d + 1):
            scored = []
            for k in order[d]:
                ps = preds.get(k, [])
                score = sum(idx[p] for p in ps if p in idx) / len(ps) if ps else idx.get(k, 0)
                scored.append((score, k))
            scored.sort(key=lambda t: t[0])
            order[d] = [k for _, k in scored]
            reindex()

        for d in range(max_d - 1, -1, -1):
            scored = []
            for k in order[d]:
                ss = succs.get(k, [])
                score = sum(idx[s] for s in ss if s in idx) / len(ss) if ss else idx.get(k, 0)
                scored.append((score, k))
            scored.sort(key=lambda t: t[0])
            order[d] = [k for _, k in scored]
            reindex()

    return order, chains, depth


def render_tree(
    nodes: list[dict[str, Any]],
    edges: list[tuple[str, str]],
    title: str = "Project Tech Tree",
    subtitle: str | None = None,
    mode: str = "lr",
) -> io.BytesIO:
    """Renders a project dependency graph into an in-memory PNG BytesIO buffer."""
    tb = mode == "tb"
    by_key = {n["key"]: n for n in nodes}

    # Handle empty state
    if not nodes:
        img = Image.new("RGB", (700, 260), BG_COLOR)
        draw = ImageDraw.Draw(img)
        draw.text((350, 90), title, font=F_TITLE, fill="#f4f9ff", anchor="mm")
        draw.text(
            (350, 140),
            "No tasks found in this project.",
            font=F_NAME,
            fill="#7a8494",
            anchor="mm",
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    order, chains, depth = plan_layout(nodes, edges)
    num_layers = max(order.keys(), default=0) + 1

    # Compute layer sizes
    layer_sizes: dict[int, int] = {}
    for d, ks in order.items():
        layer_sizes[d] = sum(DUMMY_H if k.startswith("\x00") else NODE_H for k in ks) + max(0, len(ks) - 1) * V_GAP
    max_layer_span = max(layer_sizes.values(), default=NODE_H)

    # Canvas dimensions
    if tb:
        width = PAD * 2 + max(max_layer_span, 600)
        height = PAD * 2 + TITLE_H + num_layers * NODE_H + max(0, num_layers - 1) * H_GAP
    else:
        width = PAD * 2 + max(num_layers * NODE_W + max(0, num_layers - 1) * H_GAP, 700)
        height = PAD * 2 + TITLE_H + max_layer_span

    img = Image.new("RGB", (width, height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Grid background lines
    for gx in range(0, width, 40):
        draw.line([(gx, 0), (gx, height)], fill=GRID_COLOR, width=1)
    for gy in range(0, height, 40):
        draw.line([(0, gy), (width, gy)], fill=GRID_COLOR, width=1)

    # Header Banner
    draw.rectangle([0, 0, width, TITLE_H], fill=BANNER_BG_START)
    draw.line([(0, TITLE_H), (width, TITLE_H)], fill=BORDER_LINE, width=1)

    # Title & Subtitle / Stats
    completed_n = sum(1 for n in nodes if n.get("state") == "complete")
    active_n = sum(1 for n in nodes if n.get("state") == "active")
    avail_n = sum(1 for n in nodes if n.get("state") == "available")
    locked_n = sum(1 for n in nodes if n.get("state") == "locked")
    pct_val = int((completed_n / len(nodes)) * 100) if nodes else 0

    draw.text((PAD, 24), title, font=F_TITLE, fill="#f4f9ff")
    if subtitle:
        stats_text = subtitle
    else:
        stats_text = (
            f"{len(nodes)} Tasks  •  {completed_n} Complete  •  {active_n} In Progress  •  "
            f"{avail_n} Ready  •  {locked_n} Locked  •  {pct_val}% Done"
        )
    draw.text((PAD, 58), stats_text, font=F_SUBTITLE, fill="#8b9bb0")

    # Progress bar on banner right
    prog_w = min(220, width // 4)
    prog_x = width - PAD - prog_w
    prog_y = 36
    draw.rounded_rectangle([prog_x, prog_y, prog_x + prog_w, prog_y + 14], radius=6, fill="#1c2128")
    if pct_val > 0:
        fill_px = max(10, int(prog_w * (pct_val / 100)))
        draw.rounded_rectangle([prog_x, prog_y, prog_x + fill_px, prog_y + 14], radius=6, fill="#31c77a")
    draw.text((prog_x + prog_w // 2, prog_y + 7), f"{pct_val}%", font=F_TAG, fill="#ffffff", anchor="mm")

    # Node coordinate calculation
    coords: dict[str, tuple[int, int, int, int]] = {}
    for d, ks in order.items():
        if tb:
            layer_w = sum(DUMMY_W if k.startswith("\x00") else NODE_W for k in ks) + max(0, len(ks) - 1) * V_GAP
            cur_x = (width - layer_w) // 2
            cur_y = PAD + TITLE_H + d * (NODE_H + H_GAP)
            for k in ks:
                is_dummy = k.startswith("\x00")
                w_k = DUMMY_W if is_dummy else NODE_W
                h_k = DUMMY_H if is_dummy else NODE_H
                coords[k] = (cur_x, cur_y, cur_x + w_k, cur_y + h_k)
                cur_x += w_k + V_GAP
        else:
            layer_h = sum(DUMMY_H if k.startswith("\x00") else NODE_H for k in ks) + max(0, len(ks) - 1) * V_GAP
            cur_x = PAD + d * (NODE_W + H_GAP)
            cur_y = PAD + TITLE_H + (max_layer_span - layer_h) // 2
            for k in ks:
                is_dummy = k.startswith("\x00")
                w_k = DUMMY_W if is_dummy else NODE_W
                h_k = DUMMY_H if is_dummy else NODE_H
                coords[k] = (cur_x, cur_y, cur_x + w_k, cur_y + h_k)
                cur_y += h_k + V_GAP

    def box(k: str) -> tuple[int, int, int, int]:
        return coords.get(k, (0, 0, NODE_W, NODE_H))

    def mid_x(k: str) -> int:
        b = box(k)
        return (b[0] + b[2]) // 2

    def mid_y(k: str) -> int:
        b = box(k)
        return (b[1] + b[3]) // 2

    # Draw Edges (first so nodes render over them)
    for src, dst in edges:
        if src not in depth or dst not in depth:
            continue
        lit = by_key.get(src, {}).get("state") == "complete"
        edge_color = "#31c77a" if lit else "#353d4a"
        edge_w = 3 if lit else 2

        if tb:
            waypoints = [(mid_x(src), box(src)[3])]
            for dk in chains.get((src, dst), []):
                _, ly0, _, ly1 = box(dk)
                waypoints.extend([(mid_x(dk), ly0), (mid_x(dk), ly1)])
            waypoints.append((mid_x(dst), box(dst)[1]))
        else:
            waypoints = [(box(src)[2], mid_y(src))]
            for dk in chains.get((src, dst), []):
                lx0, _, lx1, _ = box(dk)
                waypoints.extend([(lx0, mid_y(dk)), (lx1, mid_y(dk))])
            waypoints.append((box(dst)[0], mid_y(dst)))

        for (ax, ay), (bx, by) in pairwise(waypoints):
            if tb:
                mid = ay + (by - ay) // 2
                draw.line([(ax, ay), (ax, mid)], fill=edge_color, width=edge_w)
                draw.line([(ax, mid), (bx, mid)], fill=edge_color, width=edge_w)
                draw.line([(bx, mid), (bx, by)], fill=edge_color, width=edge_w)
            else:
                mid = ax + (bx - ax) // 2
                draw.line([(ax, ay), (mid, ay)], fill=edge_color, width=edge_w)
                draw.line([(mid, ay), (mid, by)], fill=edge_color, width=edge_w)
                draw.line([(mid, by), (bx, by)], fill=edge_color, width=edge_w)

        # Draw terminal connection dot
        term_x, term_y = waypoints[-1]
        draw.ellipse([term_x - 5, term_y - 5, term_x + 5, term_y + 5], fill=edge_color)

    # Draw Real Nodes
    for n in nodes:
        k = n["key"]
        state = n.get("state", "locked")
        t = THEME.get(state, THEME["locked"])
        x0, y0, x1, y1 = box(k)
        inner_w = NODE_W - 32

        # Card shadow and body
        draw.rounded_rectangle([x0 + 3, y0 + 4, x1 + 3, y1 + 4], radius=10, fill="#05070a")
        draw.rounded_rectangle([x0, y0, x1, y1], radius=10, fill=t["fill"], outline=t["edge"], width=2)
        # Left color indicator stripe
        draw.rounded_rectangle([x0, y0, x0 + 6, y1], radius=3, fill=t["accent"])

        # Top Bar: Tag badge
        badge_label = LABEL.get(state, "LOCKED")
        tag_w = draw.textlength(badge_label, font=F_TAG)
        draw.rounded_rectangle([x0 + 16, y0 + 12, x0 + 26 + tag_w, y0 + 30], radius=5, fill=t["badge_bg"])
        draw.text((x0 + 21, y0 + 16), badge_label, font=F_TAG, fill=t["badge_text"])

        # Top Bar: Short ID (e.g., [ENG-12])
        short_id = n.get("short_id", k)
        draw.text((x1 - 16, y0 + 16), short_id, font=F_TAG, fill=t["accent"], anchor="ra")

        # Task Name / Title
        cur_y = y0 + 42
        for line in _wrap(draw, n.get("name", "Untitled"), F_NAME, inner_w, 2):
            draw.text((x0 + 16, cur_y), line, font=F_NAME, fill=t["text"])
            cur_y += 20

        # Description / Blocker note
        desc = (n.get("description") or "").strip()
        if desc:
            cur_y += 2
            for line in _wrap(draw, desc, F_SMALL, inner_w, 2):
                if cur_y + 14 > y1 - 42:
                    break
                draw.text((x0 + 16, cur_y), line, font=F_SMALL, fill="#929ea8")
                cur_y += 15

        # Bottom Bar: Progress / Assignee
        bottom_y = y1 - 28
        draw.line([(x0 + 16, bottom_y - 6), (x1 - 16, bottom_y - 6)], fill=BORDER_LINE, width=1)

        # Assignee pill or text
        assignee = n.get("assignee")
        if assignee:
            assignee_label = f"👤 {assignee[:14]}"
            draw.text((x0 + 16, bottom_y), assignee_label, font=F_PILL, fill="#b5c4d4")
        else:
            draw.text((x0 + 16, bottom_y), "👤 Unassigned", font=F_PILL, fill="#626d7d")

        # Priority tag on bottom right
        priority = n.get("priority", "normal").upper()
        if priority in ("HIGH", "URGENT", "CRITICAL"):
            draw.text((x1 - 16, bottom_y), f"⚡ {priority}", font=F_PILL, fill="#ff8080", anchor="ra")
        elif priority == "LOW":
            draw.text((x1 - 16, bottom_y), "🌱 LOW", font=F_PILL, fill="#80c080", anchor="ra")

    # Downscale if exceeding Discord maximum edge limit
    if max(img.size) > MAX_EDGE:
        scale = MAX_EDGE / max(img.size)
        img = img.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
