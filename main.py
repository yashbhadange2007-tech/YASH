from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import ezdxf, ezdxf.bbox
import uuid, os, tempfile, math, re

# Import separate annotators
from civil_annotator import annotate_civil, extract_columns
from mechanical_annotator import annotate_mechanical, extract_geometry, boundary, iso_th

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
TEMP_DIR = tempfile.gettempdir()

# Robust civil-column pattern: optional F/C prefix, digits, X, digits
_CIVIL_PATTERN = re.compile(r'[FC]?\d+[Xx]\d+', re.IGNORECASE)

def detect_drawing_type(filepath):
    with open(filepath, "r", errors="ignore") as f:
        content = f.read()
    if _CIVIL_PATTERN.search(content):
        return "civil"
    return "mechanical"

@app.post("/annotate")
# FIX 1: mode MUST be Form(...) — LSP sends it as multipart form field via curl -F
# Old: mode: str = "both"  ← query param, never received from curl -F → always "both"
async def run_annotate(mode: str = Form("both"), file: UploadFile = File(...)):
    try:
        tmp = os.path.join(TEMP_DIR, f"in_{uuid.uuid4().hex}.dxf")
        with open(tmp, "wb") as f: f.write(await file.read())

        # FIX 2: Strip hidden quotes Windows CMD may inject around form values
        mode_clean = mode.replace('"', '').replace("'", "").strip().lower()

        # FIX 3: Force civil routing for all modular commands — skip auto-detect
        if mode_clean in ["columns", "beams", "centerlines", "both"]:
            drawing_type = "civil"
        else:
            drawing_type = detect_drawing_type(tmp)

        print(f"Annotating as: {drawing_type} (Mode Received: '{mode}' → Cleaned: '{mode_clean}')")

        if drawing_type == "civil":
            doc = annotate_civil(tmp, mode=mode_clean)
        else:
            doc = annotate_mechanical(tmp)

        out = os.path.join(TEMP_DIR, f"annotated_{uuid.uuid4().hex}.dxf")
        doc.saveas(out)
        os.remove(tmp)

        return FileResponse(out, media_type="application/octet-stream",
                            filename="annotated_drawing.dxf",
                            headers={"X-Type": drawing_type})
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/preview")
async def run_preview(file: UploadFile = File(...)):
    try:
        tmp = os.path.join(TEMP_DIR, f"prev_{uuid.uuid4().hex}.dxf")
        with open(tmp, "wb") as f: f.write(await file.read())

        drawing_type = detect_drawing_type(tmp)
        geo, _ = extract_geometry(tmp)
        bx1, by1, bx2, by2 = boundary(geo)
        th = iso_th(bx2 - bx1, by2 - by1)

        entities = []
        if drawing_type == "civil":
            try:
                bb = ezdxf.bbox.extents(ezdxf.readfile(tmp).modelspace())
                ext = {"x1": round(bb.extmin.x, 4), "y1": round(bb.extmin.y, 4),
                       "x2": round(bb.extmax.x, 4), "y2": round(bb.extmax.y, 4),
                       "w": round(bb.extmax.x - bb.extmin.x, 4),
                       "h": round(bb.extmax.y - bb.extmin.y, 4)}
            except:
                ext = geo.get("extents", {})
            cols = extract_columns(tmp, ext)
            entities = [{"type": "column", "label": c["label"], "size": c["size"],
                         "cx": c["cx"], "cy": c["cy"]} for c in cols]
        else:
            from mechanical_annotator import dedup_arcs, dedup_circles
            entities = (
                [{"type": "circle", "cx": c["cx"], "cy": c["cy"], "r": c["r"]} for c in geo["circles"]] +
                [{"type": "arc", "cx": a["cx"], "cy": a["cy"], "r": a["r"]} for a in geo["arcs"][:10]] +
                [{"type": "polyline", "w": p["w"], "h": p["h"]} for p in geo["polylines"][:10]]
            )
        os.remove(tmp)

        return JSONResponse({
            "drawing_type": drawing_type,
            "extents": geo.get("extents", {}),
            "actual_boundary": {"x1": round(bx1, 2), "y1": round(by1, 2),
                                 "x2": round(bx2, 2), "y2": round(by2, 2),
                                 "w": round(bx2 - bx1, 2), "h": round(by2 - by1, 2)},
            "iso_text_height": th,
            "total_entities": len(entities),
            "entities": entities[:25]
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/version")
async def get_version():
    return {
        "latest_version": "3.6",
        "message": "A new version of DXF Auto-Annotator is available! Contact Yash to upgrade for new features."
    }

@app.get("/")
def root():
    return {"status": "DXF Auto-Annotator v16 — Civil + Mechanical separate engines"}
