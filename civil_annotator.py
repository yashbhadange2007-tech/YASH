"""
Civil Drawing Annotator v15 — RIGHT-SIDE COLUMN LABELS
═══════════════════════════════════════════════════════════════════════
PLACEMENT CONVENTION:

        ███  ┌──────────┐   ← Column label placed to the RIGHT of column
        ███  │   C6    │      left edge of box = right edge of column + gap
        ███  │ 230X450 │      label text centred inside top row
        ███  └──────────┘      size  text centred inside bottom row
        ██ = column rectangle

  ┌──────┐               ← beam box placed ABOVE the beam rectangle
  │  B3  │                  bottom edge of box = top edge of beam
  └──────┘
  ══════════             ← beam rectangle below

RULES:
  • Yellow box  = column label, left edge at column right edge + gap
  • Red box     = beam label,   bottom of box aligns to beam top edge
  • Text height auto-scales so text FITS inside its box
  • No text overflow — box width always driven by text width
  • LIFT → single-row box, label only
  • Dims → outside drawing boundary
  v15 CHANGE: box_cx = col_right_edge + gap + (bw_/2)
              box_cy = col_center_y   (vertically centred on column)
═══════════════════════════════════════════════════════════════════════
"""
import ezdxf, ezdxf.bbox
import math, re, tempfile

TEMP_DIR = tempfile.gettempdir()

# DXF standard font: character drawn-width ratio.
# 0.80 is used EVERYWHERE — both for box-width calculation AND text centering
# inside draw_centred_box via tw(). Using the same constant in both places
# guarantees text is always perfectly centred with no drift.
CW = 0.80


def tw(text, height, cw=None):
    """Estimated drawn width of text string."""
    return len(text) * height * (cw if cw is not None else CW)


# ═══════════════════════════════════════════════════════════════════════════════
# COLUMN EXTRACTION  (proven — unchanged)
# ═══════════════════════════════════════════════════════════════════════════════
def extract_columns(filepath, extents):
    with open(filepath, "r", errors="ignore") as f:
        content = f.read()

    ex1 = extents["x1"] - 5;  ey1 = extents["y1"] - 5
    ex2 = extents["x2"] + 5;  ey2 = extents["y2"] + 5

    bstart = content.find("\nBLOCKS\n")
    bend   = content.find("\nENDSEC\n", bstart)
    if bstart == -1:
        return []
    blines = content[bstart:bend].split('\n')

    block_defs = {}; i = 0; current = ""
    while i < len(blines):
        code = blines[i].strip()
        if code == "BLOCK":
            bname = None; bpx = bpy = 0
            for j in range(i+1, min(i+30, len(blines))):
                bc = blines[j].strip()
                bv = blines[j+1].strip() if j+1 < len(blines) else ""
                if bc == "2" and not bname: bname = bv
                if bc == "10":
                    try: bpx = float(bv)
                    except: pass
                if bc == "20":
                    try: bpy = float(bv)
                    except: pass
                if bc in ["LINE","LWPOLYLINE","TEXT","INSERT","ENDBLK"]: break
            current = bname or ""
            block_defs[current] = {"base":(bpx,bpy), "polys":[]}
        elif code == "LWPOLYLINE" and current:
            xs=[]; ys=[]; blayer="0"
            for j in range(i+1, min(i+300, len(blines))):
                bc = blines[j].strip()
                bv = blines[j+1].strip() if j+1 < len(blines) else ""
                if bc == "8": blayer = bv
                if bc == "10":
                    try: xs.append(float(bv))
                    except: pass
                if bc == "20":
                    try: ys.append(float(bv))
                    except: pass
                if bc == "0" and j > i+5: break
            if xs and ys:
                block_defs[current]["polys"].append({
                    "cx": (max(xs)+min(xs))/2, "cy": (max(ys)+min(ys))/2,
                    "w":  round(max(xs)-min(xs), 4),
                    "h":  round(max(ys)-min(ys), 4),
                    "layer": blayer})
        i += 1

    estart = content.find("\nENTITIES\n")
    eend   = content.find("\nENDSEC\n", estart)
    elines = content[estart:eend].split('\n')
    i = 0; model_inserts = []
    while i < len(elines):
        if elines[i].strip() == "INSERT":
            name = x = y = None; rot = 0; sx = sy = 1
            for j in range(i+1, min(i+80, len(elines))):
                code = elines[j].strip()
                val  = elines[j+1].strip() if j+1 < len(elines) else ""
                if code == "2":  name = val
                if code == "10":
                    try: x = float(val)
                    except: pass
                if code == "20":
                    try: y = float(val)
                    except: pass
                if code == "41":
                    try: sx = float(val)
                    except: pass
                if code == "42":
                    try: sy = float(val)
                    except: pass
                if code == "50":
                    try: rot = float(val)
                    except: pass
                if code == "0" and j > i+5: break
            if name and x is not None:
                model_inserts.append(
                    {"name":name,"x":x,"y":y,"rot":rot,"sx":sx,"sy":sy})
        i += 1

    seen = set(); col_inserts = []
    for ins in model_inserts:
        bname = ins["name"]
        if bname not in block_defs: continue
        m = re.match(r'^([A-Za-z]+)(\d+[Xx]\d+)$', bname)
        is_lift = bname.upper() == "LIFT"
        if not m and not is_lift: continue

        bdata = block_defs[bname]
        bpx, bpy = bdata["base"]
        rot_rad = math.radians(ins["rot"])
        cos_r = math.cos(rot_rad); sin_r = math.sin(rot_rad)

        for p in bdata["polys"]:
            if "COLUMN" not in p.get("layer","").upper(): continue
            dx = p["cx"] - bpx; dy = p["cy"] - bpy
            wx = ins["x"] + ins["sx"] * (dx*cos_r - dy*sin_r)
            wy = ins["y"] + ins["sy"] * (dx*sin_r + dy*cos_r)
            wx = round(wx, 3); wy = round(wy, 3)
            if not (ex1 <= wx <= ex2 and ey1 <= wy <= ey2): continue
            key = (round(wx,1), round(wy,1))
            if key in seen: continue
            seen.add(key)

            if is_lift:
                col_type = "LIFT"; size = ""   # empty — no size row for LIFT
            elif m:
                prefix = m.group(1); size = m.group(2)
                col_type = "FC" if prefix == "FC" else "C"
                if col_type == "FC": size = "- - -"
            else:
                col_type = "C"; size = "?"

            col_inserts.append({
                "cx":wx, "cy":wy, "w":p["w"], "h":p["h"],
                "block_name":bname, "col_type":col_type, "size":size})

    if not col_inserts: return []
    col_inserts.sort(key=lambda c: (round(c["cy"],0), round(c["cx"],0)))
    fc_n = 0; c_n = 0
    for col in col_inserts:
        if   col["col_type"] == "FC":   fc_n += 1; col["label"] = f"FC{fc_n}"
        elif col["col_type"] == "LIFT": col["label"] = "LIFT"
        else:                           c_n  += 1; col["label"] = f"C{c_n}"
    return col_inserts


# ═══════════════════════════════════════════════════════════════════════════════
# BEAM EXTRACTION  (stores real x1,x2,y1,y2 of the polyline bounding box)
# ═══════════════════════════════════════════════════════════════════════════════
def extract_beams(filepath, extents):
    with open(filepath, "r", errors="ignore") as f:
        content = f.read()
    ldxf = content.split('\n')

    ex1 = extents["x1"]-1; ey1 = extents["y1"]-1
    ex2 = extents["x2"]+1; ey2 = extents["y2"]+1
    MIN_SPAN = 1.0; i = 0; raw = []

    while i < len(ldxf):
        if ldxf[i].strip() == "LWPOLYLINE":
            xs=[]; ys=[]; layer="0"
            for j in range(i+1, min(i+500, len(ldxf))):
                code = ldxf[j].strip()
                val  = ldxf[j+1].strip() if j+1 < len(ldxf) else ""
                if code == "8": layer = val
                if code == "10":
                    try: xs.append(float(val))
                    except: pass
                if code == "20":
                    try: ys.append(float(val))
                    except: pass
                if code == "0" and j > i+10: break
            if xs and ys and layer == "BEAM":
                bb_x1 = round(min(xs), 4); bb_x2 = round(max(xs), 4)
                bb_y1 = round(min(ys), 4); bb_y2 = round(max(ys), 4)
                w  = round(bb_x2 - bb_x1, 4)
                h  = round(bb_y2 - bb_y1, 4)
                cx = round((bb_x1 + bb_x2) / 2, 3)
                cy = round((bb_y1 + bb_y2) / 2, 3)
                if not (ex1 <= cx <= ex2 and ey1 <= cy <= ey2):
                    i += 1; continue
                # FIX 3: Threshold 1.5x (was 2x) catches near-square junction beams.
                # Fallback: truly square polylines classified by longer dimension.
                if w >= MIN_SPAN or h >= MIN_SPAN:
                    if w > h * 1.5:
                        o_det = "H"; span_det = w; thk_det = h
                    elif h > w * 1.5:
                        o_det = "V"; span_det = h; thk_det = w
                    else:
                        o_det = "H" if w >= h else "V"
                        span_det = w if o_det == "H" else h
                        thk_det  = h if o_det == "H" else w
                        print(f"    [WARN] near-square BEAM at ({cx},{cy}) w={w} h={h} -> {o_det}")
                    raw.append({
                        "o":o_det, "span":span_det, "thickness":thk_det,
                        "cx":cx, "cy":cy,
                        "bx1":bb_x1, "bx2":bb_x2,
                        "by1":bb_y1, "by2":bb_y2})
        i += 1

    seen = set(); filtered = []
    for b in raw:
        k = (b["o"], round(b["cx"],1), round(b["cy"],1), round(b["span"],1))
        if k not in seen: seen.add(k); filtered.append(b)

    h_b = sorted([b for b in filtered if b["o"]=="H"],
                 key=lambda b: (b["cy"], b["cx"]))
    v_b = sorted([b for b in filtered if b["o"]=="V"],
                 key=lambda b: (b["cx"], b["cy"]))
    for i, b in enumerate(h_b): b["label"] = f"B{i+1}"
    for i, b in enumerate(v_b): b["label"] = f"B{len(h_b)+i+1}"
    print(f"  Beams: {len(h_b)}H + {len(v_b)}V = {len(h_b)+len(v_b)} total")
    return h_b + v_b


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN ANNOTATOR
# ═══════════════════════════════════════════════════════════════════════════════
def annotate_civil(filepath):
    doc = ezdxf.readfile(filepath)
    msp = doc.modelspace()

    try:
        bb = ezdxf.bbox.extents(msp)
        extents = {
            "x1":round(bb.extmin.x,4), "y1":round(bb.extmin.y,4),
            "x2":round(bb.extmax.x,4), "y2":round(bb.extmax.y,4),
            "w": round(bb.extmax.x - bb.extmin.x, 4),
            "h": round(bb.extmax.y - bb.extmin.y, 4)}
    except:
        extents = {"x1":174,"y1":120,"x2":282,"y2":187,"w":108,"h":67}

    bx1 = extents["x1"]; by1 = extents["y1"]
    bx2 = extents["x2"]; by2 = extents["y2"]
    bw  = extents["w"];  bh  = extents["h"]

    col_inserts = extract_columns(filepath, extents)
    beams       = extract_beams(filepath, extents)
    print(f"  Cols:{len(col_inserts)}  Beams:{len(beams)}")
    if not col_inserts: return doc

    # ── LAYERS ────────────────────────────────────────────────────────────────
    for nm, col_no, lw in [
        ("COL_LABEL",  2, 35),   # yellow, thick border
        ("BEAM_LABEL", 1, 25),   # red,    thick border
        ("COL_DIM",    1, 25),
    ]:
        if nm not in doc.layers:
            doc.layers.new(nm, dxfattribs={"color":col_no, "lineweight":lw})

    # ── OVERALL DIM STYLING ───────────────────────────────────────────────────
    th_dim  = min([1.8,2.5,3.5,5.0,7.0], key=lambda x: abs(x - bw*0.018))
    arr_dim = round(th_dim * 1.2, 3)
    ext_off = round(th_dim * 0.5, 3)
    ds = "CIVIL_DIM"
    try:
        if ds not in doc.dimstyles:
            d = doc.dimstyles.new(ds)
            d.set_arrows(blk=ezdxf.ARROWS.closed_filled)
            d.dxf.dimtxt  = th_dim;       d.dxf.dimasz  = arr_dim
            d.dxf.dimexo  = ext_off;      d.dxf.dimexe  = ext_off*2
            d.dxf.dimgap  = th_dim*0.4;   d.dxf.dimtad  = 1
            d.dxf.dimclrd = 1;            d.dxf.dimclre = 1
            d.dxf.dimclrt = 2
    except:
        ds = "Standard"

    def arw(x, y, ang, s, lay, c):
        ax = x + s*math.cos(ang); ay = y + s*math.sin(ang)
        p  = ang + math.pi/2
        wx = s*0.35*math.cos(p);  wy = s*0.35*math.sin(p)
        msp.add_solid([(ax+wx,ay+wy),(ax-wx,ay-wy),(x,y),(ax+wx,ay+wy)],
                      dxfattribs={"layer":lay,"color":c})

    # ─────────────────────────────────────────────────────────────────────────
    # HELPER — draw a labelled box centred at (cx, cy)
    # ─────────────────────────────────────────────────────────────────────────
    def draw_centred_box(cx, cy, box_w, box_h,
                         top_text, top_th,
                         bot_text, bot_th,
                         layer, color, lw=30, cw=None, draw_box=True):
        """
        Draw a rectangle centred at (cx, cy).
        If bot_text is non-empty: two rows separated by a divider.
        If bot_text is empty:     single row with top_text only.
        Text is perfectly centred H+V inside its row.
        cw: character width ratio override (defaults to global CW=0.80)
        """
        bx   = cx - box_w / 2
        by   = cy - box_h / 2
        bx2e = bx + box_w
        by2e = by + box_h

        # Outer rectangle (skipped for beam labels — text only)
        if draw_box:
            msp.add_lwpolyline(
                [(bx,by),(bx2e,by),(bx2e,by2e),(bx,by2e),(bx,by)],
                dxfattribs={"layer":layer,"color":color,
                            "closed":True,"lineweight":lw})

        if bot_text:
            # Two rows — split box proportionally by text heights
            ratio    = top_th / (top_th + bot_th)
            top_h    = box_h * ratio
            bot_h    = box_h - top_h
            div_y    = by + bot_h

            # Divider
            msp.add_line((bx, div_y),(bx2e, div_y),
                         dxfattribs={"layer":layer,"color":color,
                                     "lineweight":max(lw//2, 13)})

            # Top row text (label: C1, FC1, etc.)
            text_w = tw(top_text, top_th, cw)
            tx = bx + (box_w - text_w) / 2
            ty = div_y + (top_h - top_th) / 2
            msp.add_text(top_text, dxfattribs={
                "insert":(tx, ty),"height":top_th,
                "layer":layer,"color":color})

            # Bottom row text (size: 230X450, etc.)
            text_w2 = tw(bot_text, bot_th, cw)
            tx2 = bx + (box_w - text_w2) / 2
            ty2 = by + (bot_h - bot_th) / 2
            msp.add_text(bot_text, dxfattribs={
                "insert":(tx2, ty2),"height":bot_th,
                "layer":layer,"color":color})
        else:
            # Single row — centre text in full box height
            text_w = tw(top_text, top_th, cw)
            tx = bx + (box_w - text_w) / 2
            ty = by + (box_h - top_th) / 2
            msp.add_text(top_text, dxfattribs={
                "insert":(tx, ty),"height":top_th,
                "layer":layer,"color":color})

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 1 — COLUMN LABEL BOXES  (centred ON column rectangle)
    # ═══════════════════════════════════════════════════════════════════════════
    for col in col_inserts:
        cx    = col["cx"]; cy = col["cy"]
        cw    = col["w"];  ch = col["h"]
        label = col["label"]
        size  = col["size"]          # "" for LIFT, "- - -" for FC
        is_lift = (col["col_type"] == "LIFT")

        # ── available area inside column ─────────────────────────────────────
        # Allow box to be LARGER than the column rectangle — text drives the size
        avail_w = cw * 1.0
        avail_h = ch * 1.0

        if is_lift:
            # Text height = fill half the column height, no global cap
            th_l = round(avail_h * 0.50, 4)
            pad  = round(th_l * 0.15, 4)
            bw_  = round(tw(label, th_l) + pad*2, 4)
            bh_  = round(th_l + pad*2, 4)

            # Place box to the RIGHT of column (v15)
            col_right = cx + cw / 2
            gap       = round(bh_ * 0.30, 4)
            box_cx    = round(col_right + gap + bw_ / 2, 4)
            box_cy    = cy

            draw_centred_box(box_cx, box_cy, bw_, bh_,
                             label, th_l,
                             "",    th_l,
                             "COL_LABEL", 2, 35)
            continue

        # ── Two-row box: label (top) + size (bottom) ──────────────────────────
        # Split column height equally between two rows, no global cap
        th_l = round(avail_h * 0.38, 4)   # label row  ~40% of col height
        th_s = round(avail_h * 0.32, 4)   # size  row  ~35% of col height

        pad    = round(th_l * 0.10, 4)
        row_l  = th_l + pad*2
        row_s  = th_s + pad*2
        total_h = row_l + row_s

        # Box width driven purely by the wider of the two texts
        bw_ = round(max(tw(label, th_l), tw(size, th_s)) + pad*2, 4)
        bh_ = round(total_h, 4)

        # Place box to the RIGHT of column
        col_right = cx + cw / 2
        gap       = round(bh_ * 0.30, 4)
        box_cx    = round(col_right + gap + bw_ / 2, 4)
        box_cy    = cy

        draw_centred_box(box_cx, box_cy, bw_, bh_,
                         label, th_l,
                         size,  th_s,
                         "COL_LABEL", 2, 35)

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 2 — BEAM LABEL BOXES  (centred ON beam rectangle)
    # ═══════════════════════════════════════════════════════════════════════════
    for beam in beams:
        cx    = beam["cx"]; cy = beam["cy"]
        label = beam["label"]
        o     = beam["o"]

        # ── REAL beam dimensions from bounding box ────────────────────────────
        if o == "H":
            beam_span = beam["bx2"] - beam["bx1"]
            beam_thk  = beam["by2"] - beam["by1"]
        else:
            beam_span = beam["by2"] - beam["by1"]
            beam_thk  = beam["bx2"] - beam["bx1"]

        if beam_thk < 0.05:
            beam_thk = beam.get("thickness", bw / 60)
        if beam_thk < 0.05:
            beam_thk = bw / 60

        # ── CHARACTER WIDTH RATIO ─────────────────────────────────────────────
        # AutoCAD romans/txt font: actual glyph width ≈ 0.66 × height.
        # We use 0.70 — accurate enough to make box snug without overflow.
        CW_BEAM = 0.70

        # ── TEXT HEIGHT ───────────────────────────────────────────────────────
        # Vertical padding inside box = 20% of beam thickness (both top+bottom).
        v_pad   = beam_thk * 0.20
        th_b    = round(beam_thk - v_pad * 2, 4)

        # Global scale guard: never smaller than bw/90, never larger than bw/18
        th_b = round(min(th_b, bw / 18), 4)
        th_b = round(max(th_b, bw / 90), 4)

        # ── BOX DIMENSIONS ────────────────────────────────────────────────────
        # Width = exact text width + horizontal padding (12% each side).
        # This makes every box exactly fit its own label — no constant-size boxes.
        h_pad  = round(th_b * 0.35, 4)          # horizontal pad each side
        text_w = len(label) * CW_BEAM * th_b
        bm_w   = round(text_w + h_pad * 2, 4)

        # Height = text height + vertical padding
        bm_h   = round(th_b + v_pad * 2, 4)

        # Safety: box height must not exceed beam thickness
        bm_h = round(min(bm_h, beam_thk), 4)

        # ── PLACEMENT ─────────────────────────────────────────────────────────
        # FIX 2: H beam → box floats ABOVE beam top edge (original correct behaviour)
        #        V beam → box placed to the RIGHT of beam right edge.
        #        Vertical beam labels placed above looked identical to H beam labels
        #        and were ambiguous/misleading on the drawing.
        if o == "H":
            beam_top = beam["by2"]
            gap_b    = round(bm_h * 0.30, 4)
            box_cx   = cx
            box_cy   = round(beam_top + gap_b + bm_h / 2, 4)
        else:
            # V beam: box sits to the RIGHT of the beam, vertically centred on beam
            beam_right = beam["bx2"]
            gap_b      = round(bm_w * 0.20, 4)   # horizontal gap = 20% of box width
            box_cx     = round(beam_right + gap_b + bm_w / 2, 4)
            box_cy     = cy   # vertically centred on beam midpoint

        draw_centred_box(box_cx, box_cy, bm_w, bm_h,
                         label, th_b,
                         "",    th_b,
                         "BEAM_LABEL", 1, 25, cw=CW_BEAM, draw_box=False)

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 3 — OVERALL DIMENSIONS  (DISABLED — overall dims removed per request)
    # ═══════════════════════════════════════════════════════════════════════════
    # dim_off = round(th_dim * 8.0, 4)

    # def h_dim_overall(p1x, p1y, p2x, p2y, base_y, txt):
    #     try:
    #         d = msp.add_linear_dim(
    #             base=(p1x, base_y), p1=(p1x, p1y), p2=(p2x, p2y),
    #             angle=0, dimstyle=ds,
    #             override={"dimtxt":th_dim,"dimasz":arr_dim,
    #                       "dimexo":ext_off,"dimexe":ext_off*2,
    #                       "dimclrd":1,"dimclrt":2,
    #                       "dimtad":1,"dimgap":th_dim*0.4},
    #             dxfattribs={"layer":"COL_DIM","color":1})
    #         d.dxf.text = txt; d.render()
    #     except:
    #         msp.add_line((p1x,p1y),(p1x,base_y),
    #                      dxfattribs={"layer":"COL_DIM","color":1})
    #         msp.add_line((p2x,p2y),(p2x,base_y),
    #                      dxfattribs={"layer":"COL_DIM","color":1})
    #         msp.add_line((p1x,base_y),(p2x,base_y),
    #                      dxfattribs={"layer":"COL_DIM","color":1})
    #         arw(p1x, base_y, 0,       arr_dim, "COL_DIM", 1)
    #         arw(p2x, base_y, math.pi, arr_dim, "COL_DIM", 1)
    #         mx = (p1x+p2x)/2
    #         msp.add_text(txt, dxfattribs={
    #             "insert":(mx - tw(txt,th_dim)/2, base_y + th_dim*0.6),
    #             "height":th_dim,"layer":"COL_LABEL","color":2})

    # def v_dim_overall(p1x, p1y, p2x, p2y, base_x, txt):
    #     try:
    #         d = msp.add_linear_dim(
    #             base=(base_x, p1y), p1=(p1x, p1y), p2=(p2x, p2y),
    #             angle=90, dimstyle=ds,
    #             override={"dimtxt":th_dim,"dimasz":arr_dim,
    #                       "dimexo":ext_off,"dimexe":ext_off*2,
    #                       "dimclrd":1,"dimclrt":2,
    #                       "dimtad":1,"dimgap":th_dim*0.4},
    #             dxfattribs={"layer":"COL_DIM","color":1})
    #         d.dxf.text = txt; d.render()
    #     except:
    #         msp.add_line((p1x,p1y),(base_x,p1y),
    #                      dxfattribs={"layer":"COL_DIM","color":1})
    #         msp.add_line((p2x,p2y),(base_x,p2y),
    #                      dxfattribs={"layer":"COL_DIM","color":1})
    #         msp.add_line((base_x,p1y),(base_x,p2y),
    #                      dxfattribs={"layer":"COL_DIM","color":1})
    #         arw(base_x, p1y,  math.pi/2, arr_dim, "COL_DIM", 1)
    #         arw(base_x, p2y, -math.pi/2, arr_dim, "COL_DIM", 1)
    #         my = (p1y+p2y)/2
    #         msp.add_text(txt, dxfattribs={
    #             "insert":(base_x - tw(txt,th_dim) - th_dim*0.5,
    #                       my - th_dim*0.5),
    #             "height":th_dim,"layer":"COL_LABEL","color":2})

    # h_dim_overall(bx1, by1, bx2, by1, by1 - dim_off, str(round(bw,2)))
    # v_dim_overall(bx1, by2, bx1, by1, bx1 - dim_off, str(round(bh,2)))

    return doc