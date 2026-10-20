from pathlib import Path
import warnings
import re
import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
except ImportError:
    go = None

HOUSEHOLDS = "Final consumption expenditure by households"
GOVERNMENT = "Final consumption expenditure by government"
NPISH = "Final consumption expenditure by non-profit organisations serving households (NPISH)"
NET_FCF = "Net fixed capital formation"
GROSS_FCF = "Gross fixed capital formation"
INVENTORIES = "Changes in inventories"
VALUABLES = "Changes in valuables"
CONSUMPTION = (HOUSEHOLDS, GOVERNMENT, NPISH)
NEGATIVE = "Negative net capital formation, changes in valuables and inventories"
DIRECT = "Direct household energy"


def _norm(value):
    return " ".join(str(value).strip().casefold().split())


def _parts(index, position):
    if isinstance(index, pd.MultiIndex):
        return pd.Index(index.get_level_values(position).astype(str))
    return pd.Index([str(v).split("|")[position] if "|" in str(v) else str(v)
                     for v in index])


def _label(value):
    if isinstance(value, tuple):
        return str(value[0]), str(value[-1])
    text = str(value)
    return tuple(text.split("|", 1)) if "|" in text else ("", text)


_LOOKUP_CACHE = {}

def _lookup(mapping, key, default=None):
    cache_id = id(mapping)
    if cache_id not in _LOOKUP_CACHE:
        normalized = {}
        for source, target in (mapping or {}).items():
            normalized.setdefault(_norm(source), target)
        _LOOKUP_CACHE[cache_id] = normalized
    return _LOOKUP_CACHE[cache_id].get(_norm(key), default)


def _find_column(columns, region, category):
    for column in columns:
        r, c = _label(column)
        if _norm(r) == _norm(region) and _norm(c) == _norm(category):
            return column
    return None


def _read_two_column(xl, sheet, left, right):
    if sheet not in xl.sheet_names:
        return {}
    data = xl.parse(sheet)
    if left not in data or right not in data:
        return {}
    return dict(zip(data[left].dropna().astype(str).str.strip(),
                    data[right].dropna().astype(str).str.strip()))


def load_maps(path, fd_sheet=None):
    """Load region, industry, final-demand, and *product* final-need maps.

    ``cons`` is deliberately built from ``final consumption`` (product rows)
    followed by ``cpi final`` (CPI columns to needs).  ``sector cons`` is an
    industry concordance and is not used as the product-to-need map.
    """
    xl = pd.ExcelFile(path)
    maps = {
        "region": _read_two_column(xl, "region prod", "region prod", "Aggregated region"),
        "sector": _read_two_column(xl, "sector prod", "sector prod", "sector prod agg"),
        "fd": {},
        "cons": {},
    }
    if "sector cons" in xl.sheet_names:
        maps["sector_cons"] = _read_two_column(xl, "sector cons", "sector cons", "sector agg")
    if fd_sheet and fd_sheet in xl.sheet_names:
        frame = xl.parse(fd_sheet)
        maps["fd"] = dict(zip(frame.iloc[:, 0].astype(str).str.strip(),
                               frame.iloc[:, 1].astype(str).str.strip()))
    if "final consumption" in xl.sheet_names:
        products = xl.parse("final consumption")
        cpi = xl.parse("cpi final") if "cpi final" in xl.sheet_names else None
        if cpi is not None:
            cpi_key = cpi.columns[0]
            product_cpi_columns = list(products.columns[1:])
            need_columns = list(cpi.columns[1:])
            for _, row in products.iterrows():
                product = str(row.iloc[0]).strip()
                allocations = []
                for cpi_col in product_cpi_columns:
                    share = row.get(cpi_col)
                    if pd.notna(share) and float(share) != 0:
                        cpi_row = cpi.loc[cpi[cpi_key].astype(str).str.strip() == cpi_col]
                        if not cpi_row.empty:
                            needs = cpi_row.iloc[0][need_columns]
                            for need, weight in needs.items():
                                if pd.notna(weight) and float(weight) != 0:
                                    need_label = {
                                        "Nourriture": "Food",
                                        "Logement": "Shelter",
                                        "Transport": "Mobility",
                                        "Textiles": "Clothing",
                                        "Santé": "Health",
                                        "Divertissements": "Recreation",
                                        "Education": "Education",
                                        "Autres biens et services": "Other goods and services",
                                    }.get(str(need), str(need))
                                    allocations.append((need_label, float(share) * float(weight)))
                if allocations:
                    total = sum(weight for _, weight in allocations)
                    maps["cons"][product] = [(need, weight / total) for need, weight in allocations]
    # Support alternate workbooks where a sheet named sector_cons is itself
    # product based, without allowing the industry map to silently win.
    for sheet in ("sector_cons", "sector cons"):
        if not maps["cons"] and sheet in xl.sheet_names:
            frame = xl.parse(sheet)
            if len(frame.columns) >= 2:
                maps["cons"] = dict(zip(frame.iloc[:, 0].astype(str).str.strip(),
                                        frame.iloc[:, 1].astype(str).str.strip()))
    return maps


def _select(F, mapping):
    names = F.index.astype(str)
    selected = {}
    for pattern, spec in mapping.items():
        label, factor = (spec, 1.0) if isinstance(spec, str) else spec
        for row in F.index[names.str.contains(pattern, case=False, regex=True)]:
            selected.setdefault(row, (label, float(factor)))
    if not selected:
        raise ValueError("No row of F matches satellite_mapping")
    rows = list(selected)
    return selected, rows, np.array([selected[row][1] for row in rows], dtype=float)


def _align_fy(F_Y, rows, ycols, factors):
    values = np.zeros((len(rows), len(ycols)))
    missing = []
    if F_Y is None:
        return values, missing
    for j, column in enumerate(ycols):
        region, category = _label(column)
        candidates = [category]
        if _norm(category) == _norm(NET_FCF):
            candidates.append(GROSS_FCF)
        if _norm(category) == _norm(GROSS_FCF):
            candidates.append(NET_FCF)
        source = None
        for candidate in candidates:
            source = _find_column(F_Y.columns, region, candidate)
            if source is not None:
                break
        if source is None:
            missing.append(column)
        else:
            values[:, j] = F_Y.loc[rows, source].to_numpy(dtype=float)
    if missing:
        warnings.warn("F_Y has no aligned column for %s; set to zero" % missing)
    return values * factors[:, None], missing

def _add(links, stage, source, target, value, source_label=None,
         target_label=None, color_key=None):
    value = float(value)
    if np.isfinite(value) and abs(value) > 1e-14:
        links.append({
            "stage": int(stage),
            "source": str(source),
            "target": str(target),
            "source_label": source_label or str(source),
            "target_label": target_label or str(target),
            "value": value,
            "color_key": color_key,
        })


def compute_footprint_flows(A, Y, x, F, F_Y, satellite_mapping,
                            target_regions, region_map, sector_map, fd_map,
                            cons_map, target_label, drop_empty_exports):
    """Compute the five-column energy-footprint Sankey flow table."""
    target_regions = [str(region) for region in target_regions]
    selected, rows, factors = _select(F, satellite_mapping)
    x = np.asarray(x, dtype=float).reshape(-1)
    S = F.loc[rows].to_numpy(dtype=float)
    S = S / np.where(x == 0, 1.0, x)[None, :]
    S = S * factors[:, None]

    year_regions = _parts(Y.columns, 0)
    categories = _parts(Y.columns, -1)
    keep = year_regions.isin(target_regions)
    if drop_empty_exports:
        keep &= ~categories.str.contains("Exports", case=False, regex=False)
    ycols = Y.columns[keep]
    cats = categories[keep].to_numpy(dtype=str)
    Yt = Y.loc[:, ycols].to_numpy(dtype=float)
    positive_Y = np.clip(Yt, 0, None)
    negative_Y = np.clip(Yt, None, 0)
    rhs = np.hstack((positive_Y, negative_Y))
    inverse = np.linalg.inv(np.eye(A.shape[0]) - np.asarray(A, dtype=float))
    Lused = inverse @ rhs
    n_y = len(ycols)
    Lpos = Lused[:, :n_y]
    Lneg = Lused[:, n_y:]

    fy, fy_missing = _align_fy(F_Y, rows, ycols, factors)
    row_index = getattr(Y, "index", pd.RangeIndex(A.shape[0]))
    row_regions = _parts(row_index, 0)
    products = np.asarray(_parts(row_index, -1), dtype=str)
    industries = np.asarray([
        _lookup(sector_map, product, "Unmapped sector") for product in products
    ], dtype=object)
    origins = np.where(np.isin(row_regions, target_regions), "Domestic", "Imports")

    s_total = S.sum(axis=0)
    sly_plus_by_row = s_total[:, None] * Lpos
    sly_minus_by_row = s_total[:, None] * Lneg
    sly_net_by_row = sly_plus_by_row + sly_minus_by_row
    positive = float(sly_plus_by_row.sum())
    negative = float(-sly_minus_by_row.sum())
    sly_net = float(sly_net_by_row.sum())
    fy_total = float(fy.sum())

    index = pd.MultiIndex.from_arrays(
        [origins, industries, products],
        names=["origin", "industry", "product"],
    )
    P = pd.DataFrame(sly_plus_by_row, index=index, columns=cats)
    N = pd.DataFrame(-sly_minus_by_row, index=index, columns=cats)
    NET = pd.DataFrame(sly_net_by_row, index=index, columns=cats)
    P = P.groupby(level=[0, 1, 2]).sum()
    N = N.groupby(level=[0, 1, 2]).sum()
    NET = NET.groupby(level=[0, 1, 2]).sum()

    net_by_origin_ind = NET.groupby(level=[0, 1]).sum().sum(axis=1)
    net_by_industry = NET.groupby(level=1).sum().sum(axis=1)
    negative_by_industry = N.groupby(level=1).sum().sum(axis=1)
    positive_by_industry = P.groupby(level=1).sum().sum(axis=1)

    links = []
    domestic = float(net_by_origin_ind[
        net_by_origin_ind.index.get_level_values(0) == "Domestic"
    ].sum())
    imports = float(net_by_origin_ind[
        net_by_origin_ind.index.get_level_values(0) == "Imports"
    ].sum())

    # Step 1: final energy use is SLYnet plus direct household energy.
    _add(links, 1, "s1|final", "s2|domestic", domestic + fy_total,
         "Final energy use", "Domestic")
    _add(links, 1, "s1|final", "s2|imports", imports,
         "Final energy use", "Imports")

    # Step 2: retain the negative source only here. It is distributed directly
    # into step-3 industry groups, so it never appears as a step-3 node.
    for (origin, industry), value in net_by_origin_ind.items():
        _add(
            links, 2,
            "s2|domestic" if origin == "Domestic" else "s2|imports",
            "s3|industry|" + str(industry),
            max(float(value), 0.0),
            "Domestic" if origin == "Domestic" else "Imports",
            str(industry),
            str(industry),
        )
    for industry, value in negative_by_industry.items():
        _add(
            links, 2, "s2|negative", "s3|industry|" + str(industry),
            max(float(value), 0.0), NEGATIVE, str(industry), str(industry),
        )
    _add(links, 2, "s2|domestic", "s3|direct", fy_total,
         "Domestic", DIRECT, "direct")

    capital_labels = {
        NET_FCF: "Positive net fixed capital formation",
        GROSS_FCF: "Positive net fixed capital formation",
        INVENTORIES: "Positive changes in inventories",
        VALUABLES: "Positive changes in valuables",
    }
    consumption_labels = {
        HOUSEHOLDS: HOUSEHOLDS,
        GOVERNMENT: GOVERNMENT,
        NPISH: NPISH,
    }
    unmapped = set()

    # Aggregate all industry/product detail into the six fixed step-4 nodes.
    # The detail is retained only in color_key, not in node IDs.
    for (_, industry, product), row in P.iterrows():
        industry_id = "s3|industry|" + str(industry)
        for category, amount in row.items():
            amount = float(amount)
            if amount <= 0:
                continue
            if category in consumption_labels:
                fce_label = consumption_labels[category]
                fce_id = "s4|consumption|" + fce_label
                _add(links, 3, industry_id, fce_id, amount,
                     str(industry), fce_label, str(industry))
                mapping = _lookup(cons_map, product)
                if mapping is None:
                    mapping = [("Unmapped product", 1.0)]
                    unmapped.add(product)
                elif isinstance(mapping, str):
                    mapping = [(mapping, 1.0)]
                for need, share in mapping:
                    _add(links, 4, fce_id, "s5|need|" + str(need),
                         amount * float(share), fce_label, str(need),
                         str(industry))
            elif category in capital_labels:
                label = capital_labels[category]
                capital_id = "s4|capital|" + label
                _add(links, 3, industry_id, capital_id, amount,
                     str(industry), label, str(industry))
                _add(links, 4, capital_id, "s5|capital", amount,
                     label, "Positive net capital formation", str(industry))

    # Direct household energy passes through an intermediate step-4 node so
    # its link does not skip a column and cross the other flows.
    _add(links, 3, "s3|direct", "s4|direct", fy_total,
         DIRECT, "Households (direct use)", "direct")
    _add(links, 4, "s4|direct", "s5|direct", fy_total,
         "Households (direct use)",
         "Direct household energy (not allocated to needs)", "direct")
    if unmapped:
        warnings.warn(
            "Unmapped products routed to Unmapped product: %s" % sorted(unmapped)
        )

    frame = pd.DataFrame(links)
    if frame.empty:
        raise ValueError("No Sankey flows were produced")
    assert not (frame.source == frame.target).any(), "Sankey contains a self-loop"

    balances = {}
    node_ids = set(frame.source) | set(frame.target)
    for node in node_ids:
        inflow = float(frame.loc[frame.target == node, "value"].sum())
        outflow = float(frame.loc[frame.source == node, "value"].sum())
        balances[node] = {
            "inflow": inflow,
            "outflow": outflow,
            "residual": inflow - outflow,
        }

    group_inflow = frame[frame.target.str.startswith("s3|industry|")].groupby(
        "target")["value"].sum()
    group_expected = positive_by_industry.copy()
    group_residual = {
        str(industry): float(group_inflow.get("s3|industry|" + str(industry), 0.0)
                             - value)
        for industry, value in group_expected.items()
    }
    assert all(abs(value) < 1e-9 for value in group_residual.values()), (
        "Step-3 industry inflow does not equal SLY+ by group: "
        + repr(group_residual)
    )
    step5_total = float(frame.loc[frame.stage == 4, "value"].sum())
    assert abs(step5_total - positive - fy_total) < 1e-9, (
        "Step-5 total does not equal SLY+ + F_Y"
    )
    diagnostics = {
        "SLY_positive": positive,
        "SLY_negative": negative,
        "SLY_net": sly_net,
        "F_Y": fy_total,
        "step5_total": step5_total,
        "step5_expected": positive + fy_total,
        "step5_residual": step5_total - positive - fy_total,
        "step3_group_residual": group_residual,
        "mass_balance": balances,
        "F_Y_missing_columns": fy_missing,
        "unmapped_products": sorted(unmapped),
        "capital_formation_type": (
            "gross" if any(_norm(c) == _norm(GROSS_FCF) for c in cats) else "net"
        ),
        "positive_by_industry": positive_by_industry.to_dict(),
        "net_by_industry": net_by_industry.to_dict(),
    }
    assumptions = [
        "SLY+ and SLY- are computed separately and SLYnet = SLY+ + SLY-.",
        "Food and shelter splits use the workbook's product/CPI weights.",
        "Direct F_Y is shown separately and is not allocated to final needs.",
    ]
    by_need = (
        frame[frame.stage == 4]
        .groupby("target_label")["value"]
        .sum()
        .sort_values(ascending=False)
        .to_frame("value")
    )
    return {
        "links": frame,
        "flows": frame.copy(),
        "by_need": by_need,
        "selected_stressors": rows,
        "totals": {
            "positive": positive,
            "negative": negative,
            "net": sly_net,
            "F_Y": fy_total,
        },
        "diagnostics": diagnostics,
        "assumptions": assumptions,
        "target_label": target_label,
    }


SAFE_RGB = [
    (136, 204, 238), (204, 102, 119), (221, 204, 119),
    (17, 119, 51), (51, 34, 136), (170, 68, 153),
    (68, 170, 153), (102, 17, 0), (0, 0, 0),
]


def _rgba(color, alpha=0.55):
    """Return rgba without depending on Plotly palettes or hex_to_rgb."""
    if color == "negative":
        rgb = (180, 60, 60)
    elif color == "direct":
        rgb = (100, 100, 100)
    elif isinstance(color, (tuple, list)) and len(color) >= 3:
        rgb = tuple(int(max(0, min(255, float(v)))) for v in color[:3])
    else:
        text = str(color or "default").strip()
        match = re.fullmatch(r"#?([0-9a-fA-F]{6})", text)
        if match:
            value = match.group(1)
            rgb = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
        else:
            match = re.fullmatch(
                r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
                r"(?:\s*,\s*[\d.]+)?\s*\)", text, flags=re.I
            )
            if match:
                rgb = tuple(int(float(match.group(i))) for i in (1, 2, 3))
            else:
                digest = sum((index + 1) * ord(char)
                             for index, char in enumerate(text))
                rgb = SAFE_RGB[digest % len(SAFE_RGB)]
    return "rgba(%d,%d,%d,%.3f)" % (*rgb, alpha)


def make_sankey(res, title, unit, min_industry_share,
                colors=None,
                height=900, width=1500,
                node_pad=18, node_thickness=18,
                font_size=11, show_legend=True,
                final_color=(90, 100, 115),
                node_color="rgba(90,100,115,0.78)"):
    """Build the Sankey figure.

    Link colours always follow the industry group (color_key), at every step.
    Vertical positions are computed by Plotly (no manual y), so nothing can
    leave the frame. Only the x position per stage is imposed.
    """
    if go is None:
        raise ImportError("plotly is required for make_sankey")
    df = res["links"].copy()
    df["color_key"] = df["color_key"].where(df["color_key"].notna(), "final")
    if df.empty:
        raise ValueError("No links available for Sankey")

    # Group small step-3 industry nodes into "Other industries".
    industry_rows = df[df.stage == 2]
    industry_totals = industry_rows.groupby("target")["value"].sum()
    small = set()
    if min_industry_share > 0 and industry_totals.sum() > 0:
        small = set(industry_totals[
            industry_totals < min_industry_share * industry_totals.sum()
        ].index)
    small_labels = {
        t.replace("s3|industry|", "") for t in small
    }
    if small:
        other_id = "s3|industry|Other industries"
        df.loc[df.source.isin(small), "source"] = other_id
        df.loc[df.target.isin(small), "target"] = other_id
        df.loc[df.source == other_id, "source_label"] = "Other industries"
        df.loc[df.target == other_id, "target_label"] = "Other industries"
        # The colour of every downstream link must follow the grouping too.
        df.loc[df.color_key.isin(small_labels), "color_key"] = "Other industries"

    # One link per (source, target, colour): colours are NOT merged anymore.
    df["color_key"] = df["color_key"].astype(str)
    grouped = (
        df.groupby(
            ["stage", "source", "target", "source_label", "target_label",
             "color_key"],
            dropna=False, as_index=False,
        )["value"].sum()
    )

    # Ghost node: forces the negative node into column 1 (same as Domestic/Imports)
    neg_id = "s2|negative"
    if neg_id in set(grouped.source) and neg_id not in set(grouped.target):
        eps = 1e-9 * float(grouped["value"].sum())
        ghost = pd.DataFrame([{
            "stage": 1, "source": "ghost|negative", "target": neg_id,
            "source_label": " ", "target_label": NEGATIVE,
            "color_key": "ghost", "value": eps,
        }])
        grouped = pd.concat([ghost, grouped], ignore_index=True)

    nodes = []
    stage_of = {}
    for row in grouped.itertuples():
        for node, label, stage in (
            (row.source, row.source_label, row.stage - 1),
            (row.target, row.target_label, row.stage),
        ):
            if node not in stage_of:
                nodes.append((node, label))
                stage_of[node] = max(0, min(4, int(stage)))
    node_ids = {node: index for index, (node, _) in enumerate(nodes)}

    # Only x is imposed; y is left to Plotly so nodes stay inside the frame.
    x_by_stage = [0.001, 0.25, 0.50, 0.75, 0.999]
    x = [x_by_stage[stage_of[node]] for node, _ in nodes]

    node_colors = [
        "rgba(0,0,0,0)" if node == "ghost|negative" else node_color
        for node, _ in nodes
    ]

    # Colours: defaults, then the user's overrides.
    group_names = sorted(
        {str(v) for v in df.color_key.dropna()}
        - {"negative", "direct", "final", "nan", "None"}
    )
    group_colors = {
        name: SAFE_RGB[index % len(SAFE_RGB)]
        for index, name in enumerate(group_names)
    }
    group_colors["negative"] = (180, 60, 60)
    group_colors["direct"] = (100, 100, 100)
    group_colors["final"] = final_color
    if colors:
        for name, value in colors.items():
            group_colors[str(name)] = value

    link_colors = [
        "rgba(0,0,0,0)" if key == "ghost"
        else _rgba(group_colors.get(key, key), 0.45)
        for key in grouped.color_key
    ]

    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node={
            "label": [label for _, label in nodes],
            "x": x,
            "pad": node_pad,
            "thickness": node_thickness,
            "color": node_colors,
        },
        link={
            "source": [node_ids[v] for v in grouped.source],
            "target": [node_ids[v] for v in grouped.target],
            "value": grouped["value"],
            "color": link_colors,
            "customdata": grouped.color_key,
            "hovertemplate": "%{source.label} → %{target.label}"
            "<br>Industry: %{customdata}<br>%{value:,.4g} " + unit
            + "<extra></extra>",
        },
    ))

    if show_legend:
        entries = [(n, group_colors[n]) for n in group_names
                   if n in set(grouped.color_key)]
        if "negative" in set(grouped.color_key):
            entries.append(("Negative capital formation flows",
                            group_colors["negative"]))
        if "direct" in set(grouped.color_key):
            entries.append(("Direct household energy", group_colors["direct"]))
        for name, color in entries:
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode="markers",
                marker=dict(size=12, color=_rgba(color, 1.0), symbol="square"),
                name=name, showlegend=True,
            ))

    fig.update_layout(
        title=title,
        height=height,
        width=width,
        font_size=font_size,
        margin=dict(l=20, r=160, t=50, b=20),
        legend=dict(title="Industry group", x=1.02, y=1.0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
    )
    return fig


def save_sankey(fig, path, scale=2):
    """
    Save the figure. The format is chosen from the file extension:
      .html            -> interactive file
      .png/.pdf/.svg   -> static image (needs the 'kaleido' package)
    scale : image resolution multiplier (png only), 2 = twice the pixels.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".html":
        fig.write_html(str(path), include_plotlyjs="cdn")
    elif suffix in (".png", ".pdf", ".svg", ".jpg", ".jpeg", ".webp"):
        fig.write_image(str(path), scale=scale)
    else:
        raise ValueError("Unsupported extension: %s" % suffix)
    return path


def export_link_table(res, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        res["links"].to_csv(path, index=False)
    else:
        res["links"].to_excel(path, index=False)
    return path
