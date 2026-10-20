"""Fonctions EXIOBASE reproduisant les opérations du notebook de référence."""
from __future__ import annotations
import os, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
def iso3_to_iso2(code: str) -> str:
    manual = {'ROM':'RO','WWA':'WA','WWE':'WE','WWF':'WF','WWL':'WL','WWM':'WM'}
    if code in manual:
        return manual[code]
    try:
        import pycountry
        result = pycountry.countries.get(alpha_3=code)
        return result.alpha_2 if result else code
    except Exception:
        return code


def load_kbar(path, key):
    import scipy.io
    mat = scipy.io.loadmat(path)
    countries_iso2 = [iso3_to_iso2(mat['countries'][i, 0][0]) for i in range(mat['countries'].shape[0])]
    sectors = [mat['prodLabels'][i, 0][0] for i in range(mat['prodLabels'].shape[0])]
    index = pd.MultiIndex.from_product([countries_iso2, sectors], names=['region', 'sector'])
    return pd.DataFrame(mat[key].toarray(), index=index, columns=index)


REQUIRED_FILES = ['Z.feather', 'Y.feather', 'x.feather', 'A.feather']


def _parse_txts(folder):
    import pyarrow.feather as feather
    for name in ['Z', 'Y', 'x', 'A']:
        if name == 'x':
            df = pd.read_csv(f"{folder}{name}.txt", sep="\t", index_col=[0, 1], header=0)
        else:
            df = pd.read_csv(f"{folder}{name}.txt", sep="\t", index_col=[0, 1], header=[0, 1])
        feather.write_feather(df, f"{folder}{name}.feather")


def _flatten_single_subfolder(folder):
    """If the ZIP was extracted as folder/IOT_xxx/..., move contents up to folder/."""
    import shutil
    folder = Path(folder)
    if (folder / "Z.txt").exists():
        return
    subs = [p for p in folder.iterdir() if p.is_dir() and (p / "Z.txt").exists()]
    if len(subs) == 1:
        for item in subs[0].iterdir():
            target = folder / item.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(item), str(target))
        subs[0].rmdir()


def setup_exiobase_tables(exio_path_zip, folder, label='newest', re_import_exiobase=False):
    """Extract one EXIOBASE archive and write Z/Y/x/A as feather."""
    Path(folder).mkdir(parents=True, exist_ok=True)
    if all(os.path.exists(folder + f) for f in REQUIRED_FILES) and not re_import_exiobase:
        print(f"✓ EXIOBASE files ({label}) exist")
        return
    print(f"Parsing EXIOBASE ({label})...")
    if not os.path.exists(exio_path_zip):
        raise FileNotFoundError(f"Missing: {exio_path_zip}")
    with zipfile.ZipFile(exio_path_zip, "r") as zf:
        zf.extractall(folder)
    _flatten_single_subfolder(folder)
    _parse_txts(folder)
    print(f"  ✓ EXIOBASE ({label}) parsed")


# ---------- x of v3.8.2 (only what 'from_x' needs) ----------
def get_x_v382(exio_path_zip_v382=None, data_folder='Data/', year=2019, system='pxp',
               version_kbar='v3.8.2', re_import_exiobase=False):
    """Return x (v3.8.2) as a Series. Read the feather if present,
    otherwise extract ONLY x.txt from the v3.8.2 ZIP and write the feather."""
    import pyarrow.feather as feather
    folder = f"{data_folder}EXIO3/IOT_{year}_{system}_{version_kbar}/"
    out = folder + "x.feather"
    if os.path.exists(out) and not re_import_exiobase:
        print(f"✓ x ({version_kbar}) feather exists")
    else:
        if exio_path_zip_v382 is None or not os.path.exists(exio_path_zip_v382):
            raise FileNotFoundError(f"{out} missing and no valid exio_path_zip_v382 "
                                    f"({exio_path_zip_v382}) to build it.")
        print(f"Extracting x.txt from {exio_path_zip_v382}...")
        Path(folder).mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(exio_path_zip_v382) as zf:
            # top-level x.txt (e.g. 'x.txt' or 'IOT_2019_pxp/x.txt'), not satellites
            cands = [n for n in zf.namelist()
                     if n.split('/')[-1] == 'x.txt' and n.count('/') <= 1]
            if not cands:
                raise FileNotFoundError(f"No x.txt found in {exio_path_zip_v382}")
            with zf.open(min(cands, key=len)) as fh:
                x_df = pd.read_csv(fh, sep="\t", index_col=[0, 1], header=0)
        feather.write_feather(x_df, out)
        print(f"  ✓ x ({version_kbar}) written: {x_df.shape}")
    x_v382 = feather.read_feather(out).fillna(0)
    return x_v382.squeeze() if isinstance(x_v382, pd.DataFrame) else x_v382


def load_matrices(data_folder='Data/', year=2019, system='pxp',
                  exio_path_zip=None, re_import_exiobase=False):
    """Read Z/A/Y/x as in the notebook. If exio_path_zip is given, (re)parse the
    archive first when files are missing or re_import_exiobase=True."""
    import pyarrow.feather as feather
    base = f'{data_folder}EXIO3/IOT_{year}_{system}/'
    if exio_path_zip is not None:
        setup_exiobase_tables(exio_path_zip, base, 'newest', re_import_exiobase)
    elif not all(os.path.exists(base + f) for f in REQUIRED_FILES):
        raise FileNotFoundError(f"Feather files missing in {base}; pass exio_path_zip to create them.")
    Z = feather.read_feather(base + 'Z.feather').fillna(0)
    A = feather.read_feather(base + 'A.feather').fillna(0)
    Y = feather.read_feather(base + 'Y.feather').fillna(0)
    x = feather.read_feather(base + 'x.feather').fillna(0)
    if isinstance(x, pd.DataFrame):
        x = x.squeeze()
    return Z, A, Y, x


def calculate_kbar_from_x(Kbar_v382, x_v382, x):
    assert Kbar_v382.index.equals(x_v382.index)
    assert Kbar_v382.index.equals(x.index)
    assert Kbar_v382.columns.equals(x_v382.index)
    assert Kbar_v382.columns.equals(x.index)
    return Kbar_v382.div(x_v382.replace(0, np.nan), axis=1).mul(x, axis=1).fillna(0)

def _load_cfc(data_folder, year, system):
    """CFC (Operating surplus: Consumption of fixed capital) by (region, sector), newest tables."""
    F = pd.read_csv(f'{data_folder}EXIO3/IOT_{year}_{system}/factor_inputs/F.txt',
                    delimiter='\t', header=[0, 1], index_col=[0])
    return F.loc['Operating surplus: Consumption of fixed capital']

def calculate_kbar_from_cfc(Kbar_v382, CFC_new):
    """Kbar_new = Kbar_v382 / CFC_v382 * CFC_new, row by row.
    Same convention as calculate_kbar_from_coefficients:
    CFC_v382 = Kbar_v382.sum(axis=1), indexed like the rows of Kbar.
    """
    CFC_new = CFC_new.reindex(Kbar_v382.index)
    cfc_old = Kbar_v382.sum(axis=1)
    assert cfc_old.index.equals(CFC_new.index), "CFC index mismatch with Kbar"
    ratio = (CFC_new / cfc_old.replace(0, np.nan)).fillna(0)
    return Kbar_v382.mul(ratio, axis=0)

# ---------- Kbar .mat -> feather (one file at a time) ----------
def get_kbar(mat_path, key, out_path, ref_index, re_import_exiobase=False):
    """Load a Kbar from .mat (cached as feather) and check labels against ref_index."""
    import pyarrow.feather as feather
    if os.path.exists(out_path) and not re_import_exiobase:
        print(f"✓ {Path(out_path).name} exists")
    else:
        if mat_path is None or not os.path.exists(mat_path):
            raise FileNotFoundError(f"{out_path} missing and .mat not found: {mat_path}")
        print(f"Loading {key} from {mat_path}...")
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        feather.write_feather(load_kbar(mat_path, key=key).fillna(0), out_path)
    K = feather.read_feather(out_path).fillna(0)
    assert K.index.equals(ref_index), f"{Path(out_path).name}: index mismatch with Z (newest)"
    assert K.columns.equals(ref_index), f"{Path(out_path).name}: columns mismatch with Z (newest)"
    print(f"  ✓ {Path(out_path).name}: {K.shape}")
    return K

# ---------- cache of the FINAL Kbar (one file per method) ----------
def kbar_result_path(data_folder, method, year, system, version_kbar='v3.8.2', base_year=2015):
    """Feather path of the computed Kbar; the method name is part of the filename."""
    if method == 'from_x':
        name = f"Kbar_from_x_{year}_{system}_{version_kbar}.feather"
    elif method == 'from_CFC':
        name = f"Kbar_from_CFC_{year}_{system}_{version_kbar}.feather"
    elif method == 'nowcasting':
        name = f"Kbar_nowcasting_{year}_{system}_base{base_year}.feather"
    else:
        raise ValueError("method must be 'from_x', 'from_CFC', or 'nowcasting'.")
    return f"{data_folder}Kbar/{name}"


def _load_cached_kbar(path, ref_index):
    """Read a computed Kbar and check it matches the current tables."""
    import pyarrow.feather as feather
    K = feather.read_feather(path).fillna(0)
    if not (K.index.equals(ref_index) and K.columns.equals(ref_index)):
        raise ValueError(f"{Path(path).name} does not match the current tables' labels. "
                         f"Rerun with recalculate_kbar=True.")
    print(f"✓ Using cached {Path(path).name}: {K.shape}")
    return K


def _save_kbar(K, path):
    import pyarrow.feather as feather
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    feather.write_feather(K, path)
    print(f"  ✓ Kbar saved to {path}")

def _wb_to_exio(df, valid_regions):
    """World Bank table (indexed by ISO3 'Country Code') -> EXIOBASE regions."""
    import country_converter as coco
    import logging
    logging.getLogger("country_converter").setLevel(logging.ERROR)  # quiet 'not found' logs
    codes = coco.convert(df.index.tolist(), src="ISO3", to="EXIO3", not_found=np.nan)
    df = df.copy()
    df.index = pd.Index(codes)
    df = df[df.index.isin(valid_regions)]           # drops aggregates (WLD, EUU, ...) and unknowns
    return df.groupby(level=0).sum(min_count=1)     # RoW countries summed into WA, WE, WF, WL, WM

def audit_wb_mapping(data_folder, base_year, target_year, valid_regions, export_path=None):
    """Show how each World Bank row was mapped to EXIOBASE regions."""
    import warnings, logging
    import country_converter as coco
    warnings.filterwarnings("ignore", category=FutureWarning, module="country_converter")
    logging.getLogger("country_converter").setLevel(logging.ERROR)

    years = [str(base_year), str(target_year)]
    read = lambda f: pd.read_excel(f"{data_folder}World Bank/{f}", header=3,
                                   index_col="Country Code")
    cfc_raw, gfcf_raw = read("CFC worldbank.xlsx"), read("GFCF worldbank.xlsx")

    iso3 = cfc_raw.index.tolist()
    audit = pd.DataFrame({
        "ISO3": iso3,
        "WB name": cfc_raw["Country Name"].values,
        "EXIO3": coco.convert(iso3, src="ISO3", to="EXIO3", not_found=np.nan),
    })
    audit["kept"] = audit["EXIO3"].isin(valid_regions)
    for y in years:   # same mask as _load_wb_ratio: data needed in both files
        audit[f"has_data_{y}"] = (cfc_raw[y].notna() & gfcf_raw.reindex(cfc_raw.index)[y].notna()).values
        audit[f"CFC_{y}"] = cfc_raw[y].values
    audit["status"] = np.select(
        [~audit["kept"], ~audit[[f"has_data_{y}" for y in years]].all(axis=1)],
        ["dropped (aggregate / unknown)", "kept but missing data"],
        default="used")

    # --- Summaries ---
    print("=== Rows dropped (should only be aggregates: WLD, EUU, HIC, ...) ===")
    print(audit.loc[~audit["kept"], ["ISO3", "WB name"]].to_string(index=False))

    print("\n=== Countries kept but with missing data (silently excluded from sums) ===")
    print(audit.loc[audit["status"] == "kept but missing data",
                    ["ISO3", "WB name", "EXIO3"]].to_string(index=False))

    print("\n=== Composition of each EXIOBASE region ===")
    used = audit[audit["status"] == "used"]
    comp = used.groupby("EXIO3")["ISO3"].agg(n="count", countries=lambda s: ", ".join(sorted(s)))
    print(comp.to_string())

    missing = sorted(set(valid_regions) - set(comp.index))
    print(f"\n=== EXIOBASE regions with no WB country: {missing} ===")  # expect ['TW'] (filled with CN)

    if export_path:
        audit.to_csv(export_path, index=False, encoding="utf-8-sig")
        print(f"\nFull table exported to {export_path}")
    return audit

def _load_wb_ratio(data_folder, base_year, target_year, valid_regions):
    """GFCF/CFC ratio from the World Bank, aggregated to EXIOBASE regions."""
    years = [str(base_year), str(target_year)]
    read = lambda f: pd.read_excel(f"{data_folder}World Bank/{f}", header=3,
                                   index_col="Country Code")[years]
    cfc, gfcf = read("CFC worldbank.xlsx"), read("GFCF worldbank.xlsx")
    mask = cfc.notna() & gfcf.notna()               # same country set in numerator and denominator
    ratio = _wb_to_exio(gfcf.where(mask), valid_regions) / _wb_to_exio(cfc.where(mask), valid_regions)
    if "TW" in valid_regions and ("TW" not in ratio.index or ratio.loc["TW"].isna().all()):
        ratio.loc["TW"] = ratio.loc["CN"]           # Taiwan is absent from World Bank data
    return ratio

def calculate_kbar_from_coefficients(Z, Y, Kbar_base, Data_folder='Data/',
                                     target_year=2019, base_year=2015, system='pxp'): # From Andrieu et al. https://github.com/baptiste-an/Mapping-global-ghg-emissions/blob/main/general_functions.py#L269
    import pyarrow.feather as feather
    Kbarcoefs = Kbar_base.div(Kbar_base.sum(axis=1), axis=0)
    Zcoefs = Z.div(Z.sum(axis=1), axis=0)
    Kbarcoefs_completed = Kbarcoefs.combine_first(Zcoefs).combine_first(pd.DataFrame(np.identity(Z.shape[0]), index=Z.index, columns=Z.columns))
    GFCF = Y.swaplevel(axis=1)['Gross fixed capital formation']
    CFC = pd.read_csv(f'{Data_folder}EXIO3/IOT_{target_year}_{system}/factor_inputs/F.txt', delimiter='\t', header=[0, 1], index_col=[0]).loc['Operating surplus: Consumption of fixed capital']
    CFC_rescaled = CFC.unstack().stack()
    try:
        regions_exio = CFC.unstack().index.unique()        # the 49 EXIOBASE codes
        ratio_wb = _load_wb_ratio(Data_folder, base_year, target_year, regions_exio)
        ratio_exio = GFCF.sum() / CFC.unstack().sum(axis=1)
        missing = set(ratio_exio.index) - set(ratio_wb.index)
        if missing:
            print(f"⚠ No WB ratio for {sorted(missing)} -> not rescaled")
        factor = (ratio_exio / ratio_wb[str(target_year)]).reindex(ratio_exio.index).fillna(1)
        CFC_rescaled = CFC.unstack().mul(factor, axis=0).stack()
        print("✓ CFC rescaled with World Bank GFCF/CFC ratios")
    except FileNotFoundError as e:
        print(f"⚠ World Bank files not found ({e}) -> CFC not rescaled")
    Kbar = Kbarcoefs_completed.mul(CFC_rescaled, axis=0)
    return Kbar.reindex(index=Z.index, columns=Z.columns, fill_value=0)


def calculate_Y_with_NFCF(Y, Kbar, save_path=None):
    import pyarrow.feather as feather
    Ym = Y.copy(deep=True); regions = Y.columns.get_level_values(0).unique(); kr = Kbar.columns.get_level_values(0); log=[]
    for dest in regions:
        gcol=(dest, 'Gross fixed capital formation')
        if gcol not in Y.columns: continue
        gv=Y[gcol]; dcols=Kbar.columns[kr==dest]
        if len(dcols)==0: nv,ct=gv,0
        else:
            cv=Kbar[dcols].sum(axis=1)
            if not gv.index.equals(cv.index): cv=cv.reindex(gv.index, fill_value=0)
            nv,ct=gv-cv,cv.sum()
        Ym[(dest,'Net fixed capital formation')]=nv; Ym=Ym.drop(columns=[gcol])
        gt,nt=gv.sum(),nv.sum(); log.append({'region':dest,'GFCF_original':gt,'CFC_subtracted':ct,'NFCF_result':nt,'check_balance':abs((gt-ct)-nt)})
    order=[(r,'Net fixed capital formation') if c=='Gross fixed capital formation' else (r,c) for r,c in Y.columns]
    Ym=Ym.reindex(columns=pd.MultiIndex.from_tuples(order,names=['region','category']))
    if save_path: feather.write_feather(Ym, save_path)
    return Ym, pd.DataFrame(log)


def extract_satellites(data_folder, year, system, indicators=None, satellite = "energy"):
    folder=f'{data_folder}/EXIO3/IOT_{year}_{system}/'
    F=pd.read_csv(folder + satellite + '/F.txt', sep='\t', index_col=0, header=[0,1])
    fy=folder + satellite + '/F_Y.txt'; FY=pd.read_csv(fy, sep='\t', index_col=0, header=[0,1]) if os.path.exists(fy) else None
    if indicators is not None:
        F=F.loc[list(indicators)]
        if FY is not None: FY=FY.loc[list(indicators)]
    return F,FY


def load_sattelite_selection(data_folder, year, system, indicator='Energy use - Final',satellite="energy"):
    F,FY=extract_satellites(data_folder,year,system,[indicator],satellite)
    return F, FY

# ---------- main entry point ----------
def generate_exiobase(data_folder='Data/', year=2019, system='pxp', *,
                      exio_path_zip, re_import_exiobase=False,
                      endogenise_capital=False, kbar_method='from_x',
                      recalculate_kbar=False,       # NEW: force recomputation of Kbar
                      version_kbar='v3.8.2', base_year=2015,
                      exio_path_zip_v382=None,
                      kbar_v382_path=None,
                      kbar_base_path=None,
                      indicator='Energy use - Final',
                      satellite="energy",):
    """Return dict(Z, A, Y, x, F, F_Y, Kbar). Kbar is None if capital not endogenised.
    - from_x:     Kbar_year(v3.8.2) / x_v3.8.2 * x_newest
    - nowcasting: Kbar_base_year coefficients * CFC (newest tables only, no v3.8.2)
    """
    Z, A, Y, x = load_matrices(data_folder, year=year, system=system,
                               exio_path_zip=exio_path_zip,
                               re_import_exiobase=re_import_exiobase)
    Kbar = None
    if endogenise_capital:
        out_path = kbar_result_path(data_folder, kbar_method, year, system,
                                    version_kbar, base_year)
        recompute = recalculate_kbar or re_import_exiobase or not os.path.exists(out_path)

        if not recompute:
            Kbar = _load_cached_kbar(out_path, x.index)

        elif kbar_method == 'from_x':
            print(f"Computing Kbar (from_x, {year})...")
            x_v382 = get_x_v382(exio_path_zip_v382, data_folder, year, system,
                                version_kbar, re_import_exiobase)
            Kbar_v382 = get_kbar(kbar_v382_path, 'Kbar',
                                 f"{data_folder}Kbar/source_Kbar_{version_kbar}_{year}_{system}.feather",
                                 x.index, re_import_exiobase)
            Kbar = calculate_kbar_from_x(Kbar_v382, x_v382, x)
            _save_kbar(Kbar, out_path)

        elif kbar_method == 'from_CFC':
            print(f"Computing Kbar (from_CFC, {year})...")
            Kbar_v382 = get_kbar(kbar_v382_path, 'Kbar',
                                 f"{data_folder}Kbar/source_Kbar_{version_kbar}_{year}_{system}.feather",
                                 x.index, re_import_exiobase)
            CFC_new = _load_cfc(data_folder, year, system)
            Kbar = calculate_kbar_from_cfc(Kbar_v382, CFC_new)
            _save_kbar(Kbar, out_path)


        elif kbar_method == 'nowcasting':
            print(f"Computing Kbar (nowcasting, base {base_year} -> {year})...")
            Kbar_base = get_kbar(kbar_base_path, 'KbarCfc',
                                 f"{data_folder}Kbar/source_KbarCfc_{base_year}_{system}.feather",
                                 x.index, re_import_exiobase)
            Kbar = calculate_kbar_from_coefficients(Z, Y, Kbar_base, Data_folder=data_folder,
                                                    target_year=year, base_year=base_year,
                                                    system=system)
            _save_kbar(Kbar, out_path)

        else:
            raise ValueError("kbar_method must be 'from_x', 'from_CFC', or 'nowcasting'.")

        Kbar = Kbar.reindex(index=Z.index, columns=Z.columns, fill_value=0)
        Y, _ = calculate_Y_with_NFCF(Y, Kbar)
        Z = Z + Kbar
        A = Z.div(x.replace(0, np.nan), axis=1).fillna(0)
    if satellite is not None :
        if isinstance(indicator, str):
            F, F_Y = load_sattelite_selection(data_folder, year, system, indicator, satellite)
        elif isinstance(indicator, list):
            F, F_Y = extract_satellites(data_folder, year, system, indicator, satellite)
        else :
            raise ValueError("indicator must be a list or a string")
    else :
        F, F_Y = None, None
    return dict(Z=Z, A=A, Y=Y, x=x, F=F, F_Y=F_Y, Kbar=Kbar)