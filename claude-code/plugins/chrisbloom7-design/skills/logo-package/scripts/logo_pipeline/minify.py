"""Shrink a composed SVG for shipping: flatten every transform into the path coordinates.

  import minify; small = minify.minify(svg_text, width=1000, digits=0)

Potrace writes ten-times-finer relative coordinates inside nested scale/translate groups. This
applies the transforms (translate, scale and nested <svg x y width height viewBox> only: everything
compose.py makes), puts the drawing in a `0 0 width h` box, rounds the absolute points (so
rounding never drifts along a path), and writes relative curves again.

<defs> (such as compose's objectBoundingBox gradients) are copied unchanged, which is only valid
for box-relative units: a gradientUnits="userSpaceOnUse" gradient, a <clipPath>, <mask> or
<pattern> raises ValueError ("not supported by minify").
Group fills and the n-* classes are kept, so the app can still recolor an inlined copy.
"""
import re
import xml.etree.ElementTree as ET

NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?|[A-Za-z]")


def parse_transform(attr):
    """Parse a transform attribute to (a, d, e, f): x' = a*x + e, y' = d*y + f (no rotate/skew)."""
    a, d, e, f = 1.0, 1.0, 0.0, 0.0
    for name, args in re.findall(r"(\w+)\(([^)]*)\)", attr or ""):
        v = [float(x) for x in re.split(r"[ ,]+", args.strip())]
        if name == "translate":
            tx, ty = v[0], (v[1] if len(v) > 1 else 0.0)
            e, f = e + a * tx, f + d * ty
        elif name == "scale":
            sx, sy = v[0], (v[1] if len(v) > 1 else v[0])
            a, d = a * sx, d * sy
        else:
            raise ValueError("unsupported transform " + name)
    return a, d, e, f


def compose_transforms(m, n):
    """m then n applied inside it (m outer): point p -> m(n(p))."""
    return (m[0] * n[0], m[1] * n[1], m[0] * n[2] + m[2], m[1] * n[3] + m[3])


def subpaths(d):
    """Parse path data to ('M', pt) / ('C', c1, c2, pt) / ('L', pt) / ('Z',) absolute points."""
    toks = NUM.findall(d)
    i, cmd, cur, start, out = 0, None, (0.0, 0.0), (0.0, 0.0), []
    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]; i += 1
            if cmd in "zZ":
                out.append(("Z",)); cur = start; continue
        n = {"M": 2, "m": 2, "L": 2, "l": 2, "C": 6, "c": 6}[cmd]
        v = [float(x) for x in toks[i:i + n]]; i += n
        rel = cmd.islower()
        ox, oy = cur if rel else (0, 0)
        pts = [(ox + v[j], oy + v[j + 1]) for j in range(0, n, 2)]
        if cmd in "Mm":
            out.append(("M", pts[0])); cur = start = pts[0]; cmd = "l" if rel else "L"
        elif cmd in "Ll":
            out.append(("L", pts[0])); cur = pts[0]
        else:
            out.append(("C", pts[0], pts[1], pts[2])); cur = pts[2]
    return out


def _fmt(v, digits):
    s = f"{v:.{digits}f}" if digits else str(int(round(v)))
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s.startswith("0."): s = s[1:]
    elif s.startswith("-0."): s = "-" + s[2:]
    return "0" if s in ("-0", "") else s


def encode_path(segs, m, digits):
    """Encode absolute segments under transform `m` as rounded relative path data."""
    a, d, e, f = m
    q = 10 ** digits
    r = lambda p: (round((a * p[0] + e) * q) / q, round((d * p[1] + f) * q) / q)
    parts, cur, last = [], (0.0, 0.0), None          # parts: command letters and formatted numbers

    def put(cmd, nums):
        nonlocal last
        if cmd != last: parts.append(cmd)
        last = cmd
        parts.extend(_fmt(x, digits) for x in nums)

    for sg in segs:
        if sg[0] == "M":
            p = r(sg[1]); put("M", p); cur = p
        elif sg[0] == "Z":
            put("z", []); last = "z"
        elif sg[0] == "L":
            p = r(sg[1]); put("l", [p[0] - cur[0], p[1] - cur[1]]); cur = p
        else:
            c1, c2, p = r(sg[1]), r(sg[2]), r(sg[3])
            put("c", [c1[0] - cur[0], c1[1] - cur[1], c2[0] - cur[0], c2[1] - cur[1],
                      p[0] - cur[0], p[1] - cur[1]])
            cur = p
    out, prev = [], ""
    for t in parts:
        if t.isalpha(): out.append(t); prev = t; continue
        if (prev and not prev.isalpha() and not t.startswith("-")
                and not (t.startswith(".") and "." in prev)):
            out.append(" ")
        out.append(t); prev = t
    return "".join(out)


def _scale_stroke(attrs, scale):
    """Stroke widths are in user units: scale them with the drawing (kept to 3 decimals)."""
    if "stroke-width" in attrs:
        attrs["stroke-width"] = _fmt(float(attrs["stroke-width"]) * abs(scale), 3)
    return attrs


def _check_defs(defs):
    """Raise unless every <defs> child uses only box-relative units (see the module docstring)."""
    for el in defs.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("clipPath", "mask", "pattern"):
            raise ValueError(f"not supported by minify: <{tag}> in <defs>")
        if el.get("gradientUnits") == "userSpaceOnUse":
            raise ValueError(f'not supported by minify: gradientUnits="userSpaceOnUse" on <{tag}>')


def minify(svg, width=1000, digits=0):
    """Flatten transforms into path coordinates, round to `digits`, scale to `width` units wide."""
    root = ET.fromstring(svg)
    vx, vy, vw, vh = (float(x) for x in root.get("viewBox").split())
    k = width / vw
    base = (k, k, -vx * k, -vy * k)
    out = ET.Element(f"{{{NS}}}svg", {"viewBox": f"0 0 {_fmt(width, 0)} {_fmt(vh * k, 0)}"})
    for key in ("width", "height"):                      # intrinsic size: keep it proportional
        if root.get(key): out.set(key, root.get(key))

    def walk(node, m, parent):
        for ch in node:
            tag = ch.tag.split("}")[1]
            if tag == "defs":
                _check_defs(ch)
                parent.append(ch)
            elif tag == "svg":
                x, y, w, h = (float(ch.get(a, 0)) for a in ("x", "y", "width", "height"))
                bx, by, bw, bh = (float(t) for t in ch.get("viewBox").split())
                inner = compose_transforms(m, (w / bw, h / bh, x - bx * w / bw, y - by * h / bh))
                walk(ch, inner, parent)
            elif tag == "g":
                attrs = {k_: v for k_, v in ch.attrib.items() if k_ != "transform"}
                mm = compose_transforms(m, parse_transform(ch.get("transform")))
                _scale_stroke(attrs, mm[0])
                if attrs:
                    g = ET.SubElement(parent, f"{{{NS}}}g", attrs); walk(ch, mm, g)
                else:
                    walk(ch, mm, parent)
            elif tag == "path":
                mm = compose_transforms(m, parse_transform(ch.get("transform")))
                attrs = {k_: v for k_, v in ch.attrib.items() if k_ not in ("transform", "d")}
                attrs["d"] = encode_path(subpaths(ch.get("d")), mm, digits)
                _scale_stroke(attrs, mm[0])
                ET.SubElement(parent, f"{{{NS}}}path", attrs)
            elif tag == "rect":
                mm = compose_transforms(m, parse_transform(ch.get("transform")))
                a, dd, e, f = mm
                at = dict(ch.attrib); at.pop("transform", None)
                for key, mult, off in (("x", a, e), ("y", dd, f)):
                    at[key] = _fmt(float(at.get(key, 0)) * mult + off, digits)
                for key, mult in (("width", a), ("height", dd)):
                    at[key] = _fmt(float(at[key]) * mult, digits)
                if "rx" in at: at["rx"] = _fmt(float(at["rx"]) * a, digits)
                ET.SubElement(parent, f"{{{NS}}}rect", at)
            elif tag in ("circle",):
                mm = compose_transforms(m, parse_transform(ch.get("transform")))
                a, dd, e, f = mm
                at = dict(ch.attrib); at.pop("transform", None)
                at["cx"] = _fmt(float(at["cx"]) * a + e, digits)
                at["cy"] = _fmt(float(at["cy"]) * dd + f, digits)
                at["r"] = _fmt(float(at["r"]) * a, digits)
                ET.SubElement(parent, f"{{{NS}}}circle", at)
            else:
                raise ValueError("unsupported element " + tag)
    walk(root, base, out)
    s = ET.tostring(out, encoding="unicode")
    if "xmlns" in s.split(">")[0]:
        return s
    return s.replace(" />", "/>").replace("<svg ", f'<svg xmlns="{NS}" ', 1)
