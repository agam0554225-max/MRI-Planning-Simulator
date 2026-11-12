from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from PIL import Image
import pydicom, numpy as np, io, uuid, zipfile
from pydicom.errors import InvalidDicomError

app = FastAPI(title="MRI Planning Simulator")
ROOT = Path(__file__).resolve().parents[1]
app.mount("/static", StaticFiles(directory=ROOT/"frontend"), name="static")
VOLUMES = {}

@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT/"frontend"/"index.html").read_text(encoding="utf-8")

@app.post("/api/volume")
async def upload_volume(files: list[UploadFile] = File(...)):
    # Accept either individual DICOM files or one ZIP containing a complete series.
    dicom_blobs = []
    total_bytes = 0
    for f in files:
        raw = await f.read()
        total_bytes += len(raw)
        if total_bytes > 200 * 1024 * 1024:
            raise HTTPException(413, "حجم الملفات أكبر من الحد المسموح (200 MB).")
        name = (f.filename or "").lower()
        if name.endswith(".zip") or raw[:4] == b"PK\x03\x04":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    entries = [x for x in archive.infolist() if not x.is_dir()]
                    if len(entries) > 10000:
                        raise HTTPException(413, "ملف ZIP يحتوي على عدد ملفات أكبر من المسموح.")
                    for item in entries:
                        if item.file_size > 100 * 1024 * 1024:
                            continue
                        if item.filename.lower().endswith((".dcm", ".dicom")):
                            dicom_blobs.append((item.filename, archive.read(item)))
            except zipfile.BadZipFile:
                raise HTTPException(400, "ملف ZIP غير صالح.")
        else:
            dicom_blobs.append((f.filename or "image.dcm", raw))

    candidates, series_counts = [], {}
    for name, raw in dicom_blobs:
        try:
            ds = pydicom.dcmread(io.BytesIO(raw), force=False)
            if not hasattr(ds, "PixelData") or not hasattr(ds, "ImagePositionPatient"):
                continue
            uid = str(getattr(ds, "SeriesInstanceUID", "unknown"))
            series_counts[uid] = series_counts.get(uid, 0) + 1
            candidates.append((uid, ds))
        except (InvalidDicomError, AttributeError, ValueError):
            continue
    if not candidates:
        raise HTTPException(400, "لم أجد صور DICOM صالحة داخل الملف.")

    chosen_uid = max(series_counts, key=series_counts.get)
    slices = []
    for uid, ds in candidates:
        if uid != chosen_uid:
            continue
        try:
            arr = ds.pixel_array.astype(np.float32)
            if arr.ndim != 2:
                continue
            ipp = np.array(ds.ImagePositionPatient, dtype=float)
            iop = np.array(ds.ImageOrientationPatient, dtype=float)
            normal = np.cross(iop[:3], iop[3:])
            projection = float(np.dot(ipp, normal))
            slices.append((projection, ipp, iop, ds, arr))
        except (AttributeError, NotImplementedError, ValueError):
            continue
    if len(slices) < 3:
        raise HTTPException(400, "لم يتم العثور على 3 شرائح DICOM صالحة على الأقل في Series واحدة.")
    slices.sort(key=lambda x: x[0])
    shape = slices[0][4].shape
    if any(s[4].shape != shape for s in slices):
        raise HTTPException(400, "أبعاد الشرائح غير متطابقة. اختَر Series واحدة.")
    ref_iop = slices[0][2]
    if any(np.max(np.abs(s[2] - ref_iop)) > 0.01 for s in slices):
        raise HTTPException(400, "اتجاه الشرائح غير متطابق داخل السلسلة.")
    normal = np.cross(ref_iop[:3], ref_iop[3:])
    if abs(normal[2]) < 0.85:
        raise HTTPException(400, "هذه النسخة تدعم حاليًا السلاسل القريبة من Axial فقط.")
    volume = np.stack([s[4] for s in slices], axis=0)
    ds = slices[0][3]
    volume = volume * float(getattr(ds, "RescaleSlope", 1)) + float(getattr(ds, "RescaleIntercept", 0))
    wc = getattr(ds, "WindowCenter", np.percentile(volume, 50))
    ww = getattr(ds, "WindowWidth", np.percentile(volume, 99) - np.percentile(volume, 1))
    if isinstance(wc, pydicom.multival.MultiValue): wc = wc[0]
    if isinstance(ww, pydicom.multival.MultiValue): ww = ww[0]
    key = str(uuid.uuid4())
    VOLUMES[key] = {
        "v": volume, "wc": float(wc), "ww": max(float(ww), 1),
        "spacing": [float(getattr(ds, "PixelSpacing", [1, 1])[0]),
                    float(getattr(ds, "PixelSpacing", [1, 1])[1]),
                    float(np.mean(np.diff([s[0] for s in slices])))],
        "patient": "De-identified training study",
        "series": str(getattr(ds, "SeriesDescription", "MRI series"))
    }
    return {"id": key, "shape": list(volume.shape), "spacing": VOLUMES[key]["spacing"],
            "patient": VOLUMES[key]["patient"], "series": VOLUMES[key]["series"],
            "slices": len(slices), "series_count": len(series_counts)}

@app.get("/api/slice/{volume_id}/{plane}/{index}")
def get_slice(volume_id:str, plane:str, index:int):
    if volume_id not in VOLUMES: raise HTTPException(404,"Volume not found")
    item=VOLUMES[volume_id]; v=item["v"]
    if plane=="axial": a=v[np.clip(index,0,v.shape[0]-1),:,:]
    elif plane=="coronal": a=v[:,np.clip(index,0,v.shape[1]-1),:]
    elif plane=="sagittal": a=v[:,:,np.clip(index,0,v.shape[2]-1)]
    else: raise HTTPException(400,"Unknown plane")
    lo=item["wc"]-item["ww"]/2; hi=item["wc"]+item["ww"]/2
    a=np.clip((a-lo)/(hi-lo),0,1)
    im=Image.fromarray((a*255).astype(np.uint8)).convert("L")
    im=im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    buf=io.BytesIO(); im.save(buf,format="PNG")
    return Response(buf.getvalue(),media_type="image/png")

@app.get("/api/info/{volume_id}")
def info(volume_id:str):
    if volume_id not in VOLUMES: raise HTTPException(404,"Volume not found")
    x=VOLUMES[volume_id]; return {"shape":list(x["v"].shape),"spacing":x["spacing"],"patient":x["patient"],"series":x["series"]}
