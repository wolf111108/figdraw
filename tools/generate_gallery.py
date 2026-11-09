"""Build a documentation contact sheet from real SVG outputs (not a composition API)."""

from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", NS)
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


def main():
    samples = [
        ("goal_success", "Grouped bars"),
        ("confidence_intervals", "Defined uncertainty"),
        ("training_curve", "Multiple series"),
        ("similarity", "Shared color scale"),
        ("memory_share", "Categorical composition"),
        ("pe_datapath", "Ports and nested groups"),
        ("experiment_flow", "Branches and loops"),
        ("pipeline", "Deterministic pipeline"),
    ]
    root = ET.Element(
        f"{{{NS}}}svg", {"width": "1000", "height": "1440", "viewBox": "0 0 1000 1440"}
    )
    ET.SubElement(root, f"{{{NS}}}rect", {"width": "1000", "height": "1440", "fill": "#F3F6FA"})
    for i, (name, title) in enumerate(samples):
        x, y = 20 + (i % 2) * 490, 20 + (i // 2) * 355
        ET.SubElement(
            root,
            f"{{{NS}}}rect",
            {"x": str(x), "y": str(y), "width": "470", "height": "335", "rx": "8", "fill": "white"},
        )
        ET.SubElement(
            root,
            f"{{{NS}}}text",
            {
                "x": str(x + 18),
                "y": str(y + 29),
                "font-family": "DejaVu Sans",
                "font-size": "16",
                "fill": "#263445",
            },
        ).text = title
        svg = ET.parse(ROOT / "output" / name / f"{name}.svg").getroot()
        # Prefix internal IDs so clip paths, markers and glyph uses remain local.
        ids = {
            el.attrib["id"]: f"gallery{i}_{el.attrib['id']}"
            for el in svg.iter()
            if "id" in el.attrib
        }
        for el in svg.iter():
            for key, value in list(el.attrib.items()):
                if key == "id":
                    el.set(key, ids[value])
                else:
                    for old, new in ids.items():
                        value = value.replace(f"url(#{old})", f"url(#{new})")
                        if value == f"#{old}":
                            value = f"#{new}"
                    el.set(key, value)
        svg.attrib.update(x=str(x + 12), y=str(y + 40), width="446", height="280")
        root.append(svg)
    out = ROOT / "docs/gallery/overview.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    print(out)


if __name__ == "__main__":
    main()
