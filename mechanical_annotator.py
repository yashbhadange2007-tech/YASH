"""
Mechanical Drawing Annotator
Handles: Radius leaders, diameter annotations, linear dimensions
"""
import ezdxf, ezdxf.bbox
import math, uuid, os, tempfile
from collections import defaultdict

TEMP_DIR = tempfile.gettempdir()

class Placer:
    def __init__(self, pad):
        self.boxes=[]; self.pad=pad
    def add(self,x1,y1,x2,y2): self.boxes.append((x1,y1,x2,y2))
    def free(self,x1,y1,x2,y2):
        p=self.pad
        for bx1,by1,bx2,by2 in self.boxes:
            if not (x2+p<bx1 or x1-p>bx2 or y2+p<by1 or y1-p>by2): return False
        return True
    def find(self,ax,ay,w,h,min_dist,angles=None):
        if angles is None:
            angles=[45,0,90,135,180,225,270,315,30,60,120,150,210,240,300,330,15,75,105,165,195,255,285,345]
        for dist in [min_dist,min_dist*1.8,min_dist*2.8,min_dist*4.0,min_dist*5.5,min_dist*7.0]:
            for deg in angles:
                rad=math.radians(deg); cx=ax+dist*math.cos(rad); cy=ay+dist*math.sin(rad)
                x1=cx-w/2; y1=cy-h/2; x2=cx+w/2; y2=cy+h/2
                if self.free(x1,y1,x2,y2):
                    self.add(x1,y1,x2,y2); return x1,y1,cx,cy
        mx=max((b[2] for b in self.boxes),default=ax+min_dist)
        x1=mx+self.pad*2; y1=ay-h/2; self.add(x1,y1,x1+w,y1+h)
        return x1,y1,x1+w/2,y1+h/2

def extract_geometry(filepath):
    doc=ezdxf.readfile(filepath); msp=doc.modelspace()
    geo={"circles":[],"arcs":[],"polylines":[],"lines":[],"splines":[]}
    for e in msp:
        try:
            t=e.dxftype()
            if t=="CIRCLE":
                geo["circles"].append({"cx":round(e.dxf.center.x,4),"cy":round(e.dxf.center.y,4),"r":round(e.dxf.radius,4)})
            elif t=="ARC":
                geo["arcs"].append({"cx":round(e.dxf.center.x,4),"cy":round(e.dxf.center.y,4),"r":round(e.dxf.radius,4),"sa":round(e.dxf.start_angle,2),"ea":round(e.dxf.end_angle,2)})
            elif t=="LWPOLYLINE":
                pts=[(round(p[0],4),round(p[1],4)) for p in e.get_points()]
                if len(pts)>=2:
                    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                    geo["polylines"].append({"pts":pts,"w":round(max(xs)-min(xs),4),"h":round(max(ys)-min(ys),4),"x1":round(min(xs),4),"y1":round(min(ys),4),"x2":round(max(xs),4),"y2":round(max(ys),4)})
            elif t=="LINE":
                geo["lines"].append({"x1":round(e.dxf.start.x,4),"y1":round(e.dxf.start.y,4),"x2":round(e.dxf.end.x,4),"y2":round(e.dxf.end.y,4),"length":round(math.hypot(e.dxf.end.x-e.dxf.start.x,e.dxf.end.y-e.dxf.start.y),4)})
            elif t=="SPLINE":
                pts=[(round(p[0],4),round(p[1],4)) for p in e.control_points]
                if pts:
                    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
                    geo["splines"].append({"pts":pts[:8],"x1":round(min(xs),4),"y1":round(min(ys),4),"x2":round(max(xs),4),"y2":round(max(ys),4)})
        except: continue
    try:
        bb=ezdxf.bbox.extents(msp)
        geo["extents"]={"x1":round(bb.extmin.x,4),"y1":round(bb.extmin.y,4),"x2":round(bb.extmax.x,4),"y2":round(bb.extmax.y,4),"w":round(bb.extmax.x-bb.extmin.x,4),"h":round(bb.extmax.y-bb.extmin.y,4)}
    except: geo["extents"]={}
    return geo, doc

def boundary(geo):
    ax=[]; ay=[]
    for p in geo.get("polylines",[]):
        for pt in p.get("pts",[]): ax.append(pt[0]); ay.append(pt[1])
    for l in geo.get("lines",[]): ax+=[l["x1"],l["x2"]]; ay+=[l["y1"],l["y2"]]
    for a in geo.get("arcs",[]):
        cx,cy,r=a["cx"],a["cy"],a["r"]; sa,ea=a["sa"],a["ea"]
        if ea<sa: ea+=360
        for k in range(int((ea-sa)/5)+2):
            ang=math.radians(sa+(ea-sa)*k/max(int((ea-sa)/5)+1,1))
            ax.append(cx+r*math.cos(ang)); ay.append(cy+r*math.sin(ang))
    for s in geo.get("splines",[]):
        for pt in s.get("pts",[]): ax.append(pt[0]); ay.append(pt[1])
    for c in geo.get("circles",[]):
        ax+=[c["cx"]-c["r"],c["cx"]+c["r"]]; ay+=[c["cy"]-c["r"],c["cy"]+c["r"]]
    if not ax:
        e=geo.get("extents",{}); return e.get("x1",0),e.get("y1",0),e.get("x2",100),e.get("y2",100)
    return min(ax),min(ay),max(ax),max(ay)

def iso_th(w,h):
    ideal=math.hypot(w,h)*0.030
    return min([1.8,2.5,3.5,5.0,7.0,10.0,14.0,20.0],key=lambda x:abs(x-ideal))

def dedup_arcs(arcs):
    groups=defaultdict(list)
    for a in arcs:
        key=(round(a["cx"],1),round(a["cy"],1),round(a["r"],1))
        groups[key].append(a)
    seen_r=set(); result=[]
    for key,grp in groups.items():
        r_key=round(grp[0]["r"],1)
        if r_key in seen_r: continue
        seen_r.add(r_key)
        best=max(grp,key=lambda a:(a["ea"]-a["sa"]) if a["ea"]>=a["sa"] else (a["ea"]+360-a["sa"]))
        result.append(best)
    return result

def dedup_circles(circles):
    seen=set(); result=[]
    for c in circles:
        key=(round(c["cx"],1),round(c["cy"],1))
        if key not in seen: seen.add(key); result.append(c)
    return result

def line_crosses_box(lx1,ly1,lx2,ly2,bx1,by1,bx2,by2):
    def cross(ax,ay,bx,by,cx,cy,dx,dy):
        def ccw(ax,ay,bx,by,cx,cy): return (cy-ay)*(bx-ax)>(by-ay)*(cx-ax)
        return (ccw(ax,ay,cx,cy,dx,dy)!=ccw(bx,by,cx,cy,dx,dy) and ccw(ax,ay,bx,by,cx,cy)!=ccw(ax,ay,bx,by,dx,dy))
    for ex1,ey1,ex2,ey2 in [(bx1,by1,bx2,by1),(bx2,by1,bx2,by2),(bx2,by2,bx1,by2),(bx1,by2,bx1,by1)]:
        if cross(lx1,ly1,lx2,ly2,ex1,ey1,ex2,ey2): return True
    return False

def annotate_mechanical(filepath):
    """Main mechanical annotation function"""
    geo,doc=extract_geometry(filepath)
    msp=doc.modelspace()
    bx1,by1,bx2,by2=boundary(geo)
    bw=bx2-bx1; bh=by2-by1

    th=iso_th(bw,bh); arr=round(th*1.2,3); ext_off=round(th*0.5,3)
    gap=round(th*0.6,3); cw=round(th*0.60,3); lh=round(th*1.5,3)
    dim_off=round(th*6.0,3); dim_off2=round(th*13.0,3); pad=round(th*2.5,3)

    P=Placer(pad); P.add(bx1-th*4,by1-th*4,bx2+th*4,by2+th*4)

    for nm,col,lw in [("DIM",1,25),("LABEL",2,18),("LEADER",3,18)]:
        if nm not in doc.layers:
            doc.layers.new(nm,dxfattribs={"color":col,"lineweight":lw})

    ds="AI_ISO"
    try:
        if ds not in doc.dimstyles:
            d=doc.dimstyles.new(ds)
            d.set_arrows(blk=ezdxf.ARROWS.closed_filled)
            d.dxf.dimtxt=th; d.dxf.dimasz=arr; d.dxf.dimexo=ext_off
            d.dxf.dimexe=ext_off*2.5; d.dxf.dimgap=gap*0.8; d.dxf.dimtad=1
            d.dxf.dimclrd=1; d.dxf.dimclre=1; d.dxf.dimclrt=2
            d.dxf.dimtih=0; d.dxf.dimtoh=0
    except: ds="Standard"

    def arw(x,y,ang,s=None,lay="DIM",col=1):
        s=s or arr; ax=x+s*math.cos(ang); ay=y+s*math.sin(ang)
        p=ang+math.pi/2; wx=s*0.35*math.cos(p); wy=s*0.35*math.sin(p)
        msp.add_solid([(ax+wx,ay+wy),(ax-wx,ay-wy),(x,y),(ax+wx,ay+wy)],dxfattribs={"layer":lay,"color":col})

    def h_dim(p1x,p1y,p2x,p2y,base_y,txt=None):
        lbl=txt or str(round(abs(p2x-p1x),2))
        try:
            d=msp.add_linear_dim(base=(p1x,base_y),p1=(p1x,p1y),p2=(p2x,p2y),angle=0,dimstyle=ds,
                override={"dimtxt":th,"dimasz":arr,"dimexo":ext_off,"dimexe":ext_off*2.5,"dimclrd":1,"dimclrt":2,"dimtad":1,"dimgap":gap*0.8},
                dxfattribs={"layer":"DIM","color":1})
            if txt: d.dxf.text=txt
            d.render()
            mx=(p1x+p2x)/2; lw2=len(lbl)*cw+gap
            P.add(mx-lw2/2,base_y+gap*0.5,mx+lw2/2,base_y+gap*0.5+lh)
        except Exception as ex:
            msp.add_line((p1x,p1y),(p1x,base_y-ext_off),dxfattribs={"layer":"DIM","color":1})
            msp.add_line((p2x,p2y),(p2x,base_y-ext_off),dxfattribs={"layer":"DIM","color":1})
            msp.add_line((p1x,base_y),(p2x,base_y),dxfattribs={"layer":"DIM","color":1})
            arw(p1x,base_y,0); arw(p2x,base_y,math.pi)
            mx=(p1x+p2x)/2; lw2=len(lbl)*cw+gap; ty=base_y+gap*0.8
            P.add(mx-lw2/2,ty,mx+lw2/2,ty+lh)
            msp.add_text(lbl,dxfattribs={"insert":(mx-lw2/2,ty),"height":th,"layer":"LABEL","color":2})

    def v_dim(p1x,p1y,p2x,p2y,base_x,txt=None):
        lbl=txt or str(round(abs(p2y-p1y),2))
        try:
            d=msp.add_linear_dim(base=(base_x,p1y),p1=(p1x,p1y),p2=(p2x,p2y),angle=90,dimstyle=ds,
                override={"dimtxt":th,"dimasz":arr,"dimexo":ext_off,"dimexe":ext_off*2.5,"dimclrd":1,"dimclrt":2,"dimtad":1,"dimgap":gap*0.8},
                dxfattribs={"layer":"DIM","color":1})
            if txt: d.dxf.text=txt
            d.render()
            my=(p1y+p2y)/2; lw2=len(lbl)*cw+gap
            P.add(base_x-lw2-gap*1.5,my-lh/2,base_x,my+lh/2)
        except Exception as ex:
            msp.add_line((p1x,p1y),(base_x-ext_off,p1y),dxfattribs={"layer":"DIM","color":1})
            msp.add_line((p2x,p2y),(base_x-ext_off,p2y),dxfattribs={"layer":"DIM","color":1})
            msp.add_line((base_x,p1y),(base_x,p2y),dxfattribs={"layer":"DIM","color":1})
            arw(base_x,p1y,math.pi/2); arw(base_x,p2y,-math.pi/2)
            my=(p1y+p2y)/2; lw2=len(lbl)*cw+gap; tx=base_x-lw2-gap*1.2; ty=my-th*0.5
            P.add(tx,ty,tx+lw2,ty+lh)
            msp.add_text(lbl,dxfattribs={"insert":(tx,ty),"height":th,"layer":"LABEL","color":2})

    def r_leader(cx,cy,r,mid_deg,txt):
        ang=math.radians(mid_deg); tip_x=cx+r*math.cos(ang); tip_y=cy+r*math.sin(ang)
        arw(tip_x,tip_y,ang+math.pi,arr,"LEADER",3)
        w2=len(txt)*cw+gap*0.3; h2=lh; min_dist=r+dim_off*0.8
        dcx=(bx1+bx2)/2; dcy=(by1+by2)/2
        away=math.degrees(math.atan2(cy-dcy,cx-dcx))
        pref=[away,away+40,away-40,away+80,away-80,away+120,away-120,away+160,away-160,mid_deg,mid_deg+60,mid_deg-60,0,45,90,135,180,225,270,315]
        tx=ty=tcx=tcy=None
        for dist in [min_dist,min_dist*1.8,min_dist*2.8,min_dist*4.0,min_dist*5.5]:
            for deg in pref:
                rad2=math.radians(deg); lcx=cx+dist*math.cos(rad2); lcy=cy+dist*math.sin(rad2)
                lx1=lcx-w2/2; ly1=lcy-h2/2; lx2=lcx+w2/2; ly2=lcy+h2/2
                if not P.free(lx1,ly1,lx2,ly2): continue
                if line_crosses_box(tip_x,tip_y,lcx,lcy,bx1+th*2,by1+th*2,bx2-th*2,by2-th*2): continue
                P.add(lx1,ly1,lx2,ly2); tx,ty,tcx,tcy=lx1,ly1,lcx,lcy; break
            if tx is not None: break
        if tx is None: tx,ty,tcx,tcy=P.find(cx,cy,w2,h2,min_dist,pref)
        jx=tx+w2/2; shoulder_y=ty
        msp.add_line((tip_x,tip_y),(jx,shoulder_y),dxfattribs={"layer":"LEADER","color":3,"lineweight":18})
        sh_x1,sh_x2=(jx,tx+w2) if jx>=tip_x else (tx,jx)
        msp.add_line((sh_x1,shoulder_y),(sh_x2,shoulder_y),dxfattribs={"layer":"LEADER","color":3,"lineweight":18})
        msp.add_text(txt,dxfattribs={"insert":(tx,shoulder_y+gap*0.25),"height":th,"layer":"LABEL","color":2})

    def d_ann(cx,cy,r,txt):
        msp.add_line((cx-r,cy),(cx+r,cy),dxfattribs={"layer":"DIM","color":1,"lineweight":25})
        arw(cx-r,cy,0,arr,"DIM",1); arw(cx+r,cy,math.pi,arr,"DIM",1)
        w2=len(txt)*cw+gap*0.3; h2=lh; min_dist=r+dim_off*0.9
        pref=[90,70,110,50,130,45,135,30,150,20,160,0,180,270,225,315]
        tx=ty=tcx=tcy=None
        for dist in [min_dist,min_dist*1.8,min_dist*2.8,min_dist*4.0]:
            for deg in pref:
                rad2=math.radians(deg); lcx=cx+dist*math.cos(rad2); lcy=cy+dist*math.sin(rad2)
                lx1=lcx-w2/2; ly1=lcy-h2/2; lx2=lcx+w2/2; ly2=lcy+h2/2
                if not P.free(lx1,ly1,lx2,ly2): continue
                if line_crosses_box(cx+r,cy,lcx,lcy,bx1+th,by1+th,bx2-th,by2-th): continue
                P.add(lx1,ly1,lx2,ly2); tx,ty,tcx,tcy=lx1,ly1,lcx,lcy; break
            if tx is not None: break
        if tx is None: tx,ty,tcx,tcy=P.find(cx,cy,w2,h2,min_dist,pref)
        jx=tx+w2/2; jy=ty
        msp.add_line((cx+r,cy),(jx,jy),dxfattribs={"layer":"LEADER","color":3,"lineweight":13})
        sh_x1,sh_x2=(jx,tx+w2) if jx>=cx+r else (tx,jx)
        msp.add_line((sh_x1,jy),(sh_x2,jy),dxfattribs={"layer":"LEADER","color":3,"lineweight":13})
        msp.add_text(txt,dxfattribs={"insert":(tx,jy+gap*0.25),"height":th,"layer":"LABEL","color":2})

    # CIRCLES
    for c in dedup_circles(geo.get("circles",[])):
        d_ann(c["cx"],c["cy"],c["r"],f"%%C{round(c['r']*2,2)}")

    # ARCS
    for a in dedup_arcs(geo.get("arcs",[])):
        sa,ea=a["sa"],a["ea"]
        if ea<sa: ea+=360
        r_leader(a["cx"],a["cy"],a["r"],(sa+ea)/2,f"R{round(a['r'],2)}")

    # POLYLINES
    polys=sorted(geo.get("polylines",[]),key=lambda p:p["w"]*p["h"],reverse=True)
    seen_w=set(); seen_h=set()
    arcs_dd=dedup_arcs(geo.get("arcs",[]))
    for i,p in enumerate(polys[:6]):
        pts=p["pts"]; pw=round(p["w"],2); ph=round(p["h"],2)
        if pw<th*3 or ph<th*3: continue
        sx=sorted(pts,key=lambda pt:pt[0]); sy=sorted(pts,key=lambda pt:pt[1])
        lpt=sx[0]; rpt=sx[-1]; bpt=sy[0]; tpt=sy[-1]
        step=dim_off*(1+i*2.2)
        wk=round(pw,1)
        if wk not in seen_w:
            seen_w.add(wk)
            is_slot=pw>ph*1.5
            if is_slot:
                slot_arcs=[a for a in arcs_dd if abs(a["cy"]-(p["y1"]+ph/2))<ph*0.6 and a["r"]<pw*0.4]
                if len(slot_arcs)>=2:
                    sa2=sorted(slot_arcs,key=lambda a:a["cx"]); lc=sa2[0]; rc=sa2[-1]
                    h_dim(lc["cx"],lc["cy"],rc["cx"],rc["cy"],tpt[1]+step*0.5,str(round(rc["cx"]-lc["cx"],2)))
                else:
                    h_dim(lpt[0],lpt[1],rpt[0],rpt[1],tpt[1]+step*0.5,str(pw))
            else:
                h_dim(lpt[0],lpt[1],rpt[0],rpt[1],bpt[1]-step,str(pw))
        hk=round(ph,1)
        if hk not in seen_h:
            seen_h.add(hk); v_dim(rpt[0],bpt[1],rpt[0],tpt[1],rpt[0]+step,str(ph))

    # SPLINES
    seen_sw=set(); seen_sh=set()
    for i,s in enumerate(geo.get("splines",[])[:3]):
        sx1,sy1,sx2,sy2=s["x1"],s["y1"],s["x2"],s["y2"]
        sw=round(sx2-sx1,2); sh=round(sy2-sy1,2)
        if sw<th*3 or sh<th*3: continue
        step=dim_off*(1+i*0.9)
        if round(sw,1) not in seen_sw: seen_sw.add(round(sw,1)); h_dim(sx1,sy1,sx2,sy1,sy1-step,str(sw))
        if round(sh,1) not in seen_sh: seen_sh.add(round(sh,1)); v_dim(sx2,sy1,sx2,sy2,sx2+step,str(sh))

    # SIGNIFICANT LINES
    min_line=bw*0.06; seen_ll=set()
    for l in geo.get("lines",[]):
        if l["length"]<min_line: continue
        lk=round(l["length"],1)
        if lk in seen_ll: continue
        seen_ll.add(lk)
        x1,y1,x2,y2=l["x1"],l["y1"],l["x2"],l["y2"]
        if abs(y2-y1)<abs(x2-x1)*0.1: h_dim(x1,y1,x2,y2,min(y1,y2)-dim_off,str(round(l["length"],2)))
        elif abs(x2-x1)<abs(y2-y1)*0.1: v_dim(x1,y1,x2,y2,max(x1,x2)+dim_off,str(round(l["length"],2)))

    # OVERALL
    h_dim(bx1,by1,bx2,by1,by1-dim_off2,str(round(bw,2)))
    v_dim(bx1,by2,bx1,by1,bx1-dim_off2,str(round(bh,2)))

    return doc