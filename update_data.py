# -*- coding: utf-8 -*-
"""
韩国股市资金面·杠杆监测台 —— 数据更新脚本
用法:  python update_data.py        (与 韩国资金面杠杆监测台.html 放在同一文件夹)
依赖:  pip install requests
产出:  data.js (网页自动读取) + data_backup.json

数据源与频率:
  [必有] ECOS 802Y001  KOSPI总市值        日频  1995年起   (韩银接口, 密钥已内置)
  [必有] ECOS 104Y015  活期/储蓄性存款     月频  1990年起
  [必有] ECOS 901Y056  协会资金面(转发)    月频  长历史     (预托金/融资/RP/垫付/CMA)
  [可选] data.go.kr    协会资金面(原始)    日频  全历史     (需在下方填入公共数据门户密钥)
         → 免费注册 data.go.kr → 搜「금융투자협회종합통계」(编号15094809) → 활용신청(自动批准)
"""
import json, math, os, sys, time, datetime as dt
try:
    import requests
except ImportError:
    sys.exit("请先安装依赖:  pip install requests")

# ============================= 密钥配置 =============================
ECOS_KEY = os.environ.get("ECOS_KEY") or "CYKDMCR9HNSZMQ8JBR50"          # 韩国银行ECOS (已填)
DATA_GO_KR_KEY = os.environ.get("DATA_GO_KR_KEY") or ""                         # 公共数据门户通用密钥(Encoding/Decoding均可试), 留空则协会数据用ECOS月频
# ===================================================================

DEBUG=[]   # 诊断信息, 会写入 data_backup.json 的 meta.debug 供远程排查
def dbg(msg):
    print("   [诊断]", msg, flush=True); DEBUG.append(str(msg)[:300])

TODAY = dt.date.today()
YM  = TODAY.strftime("%Y%m")
YMD = TODAY.strftime("%Y%m%d")

# 单位自校准锚点: 2026-06月末已知值(万亿韩元, 来自协会官网底稿)
ANCHOR = {"yetak":121.6, "yungja":37.3, "jiya":25.5, "rp":108.8, "misu":1.3, "cma":110.5}


# 合理区间(万亿韩元): 数量级校准的硬约束
RANGE = {"mcap":(800,12000),"demand":(200,2000),"time":(400,3000),"hhloan":(600,2500),
         "yetak":(5,400),"yungja":(1,120),"jiya":(1,120),"rp":(5,400),"misu":(0.05,20),"cma":(5,400)}
def calibrate(key, raw_latest, unit_name):
    """先按单位字段换算, 若落在合理区间直接用; 否则在10的幂里找能落区间的档位"""
    lo,hi = RANGE.get(key,(0.01,20000))
    base = unit_scale_by_name(unit_name)
    if lo <= raw_latest*base <= hi: return base
    for s in (1,0.1,0.01,1e-3,1e-4,1e-5,1e-6,1e-7,1e-8,1e-9,1e-10,1e-11,1e-12,1e-13):
        if lo <= raw_latest*s <= hi: return s
    return None

def unit_scale_by_name(u):
    u = u or ""
    if "조" in u: return 1.0
    if "천억" in u: return 0.1
    if "십억" in u: return 1e-3
    if "백만" in u: return 1e-6
    if "억" in u: return 1e-4
    if u.strip()=="원": return 1e-12
    return 1e-3

def snap_scale(raw_latest, anchor):
    """在10的幂中选使 raw*scale ≈ anchor 的档位"""
    if not raw_latest or raw_latest <= 0: return None
    best, bd = None, 9e9
    for s in (1,0.1,0.01,1e-3,1e-4,1e-5,1e-6,1e-7,1e-8,1e-9,1e-10,1e-11,1e-12,1e-13):
        d = abs(math.log10(raw_latest*s) - math.log10(anchor))
        if d < bd: bd, best = d, s
    return best if bd < 0.5 else None   # 偏离超过~3倍则放弃校准

# ---------------------------- ECOS ----------------------------
E = "https://ecos.bok.or.kr/api"
def ecos(path):
    r = requests.get(f"{E}/{path}", timeout=60); r.raise_for_status()
    j = r.json()
    res = j.get("RESULT")
    if res and res.get("CODE") not in (None,"INFO-000"):
        if res.get("CODE")=="INFO-200":   # 区间内无数据 → 视为空
            return {}
        raise RuntimeError(f"ECOS: {res.get('CODE')} {res.get('MESSAGE')}")
    return j

def ecos_items(stat):
    j = ecos(f"StatisticItemList/{ECOS_KEY}/json/kr/1/500/{stat}")
    rows = (j.get("StatisticItemList") or {}).get("row") or []
    if not rows:
        dbg(f"{stat} 项目清单为空, 原始返回键={list(j.keys())} RESULT={j.get('RESULT')}")
    return rows

def ecos_series_all(stat, cyc, s, e):
    """不指定项目 → 返回该表全部项目的行(带ITEM_NAME1字段), 绕开项目清单接口"""
    j = ecos(f"StatisticSearch/{ECOS_KEY}/json/kr/1/100000/{stat}/{cyc}/{s}/{e}/")
    return (j.get("StatisticSearch") or {}).get("row") or []

def ecos_series(stat, cyc, item, s, e):
    rows = ecos(f"StatisticSearch/{ECOS_KEY}/json/kr/1/100000/{stat}/{cyc}/{s}/{e}/{item}")
    return rows.get("StatisticSearch",{}).get("row",[])

def rows_to_pairs(rows):
    out=[]
    for r in rows:
        t, v = r.get("TIME",""), r.get("DATA_VALUE")
        try: v=float(v)
        except (TypeError,ValueError): continue
        if len(t)>=8: d=f"{t[:4]}-{t[4:6]}-{t[6:8]}"
        elif len(t)>=6: d=f"{t[:4]}-{t[4:6]}"
        else: continue
        out.append((d,v))
    return sorted(out)

def fetch_mcap():
    print("· KOSPI总市值(日频, ECOS 802Y001)…", flush=True)
    items = ecos_items("802Y001")
    it = next((r for r in items if "시가총액" in (r.get("ITEM_NAME") or "") and "코스닥" not in (r.get("ITEM_NAME") or "")), None)
    if not it:
        print("  项目清单:", [r.get("ITEM_NAME") for r in items][:30])
        raise RuntimeError("802Y001 未找到市值项目(清单已打印)")
    pairs = rows_to_pairs(ecos_series("802Y001","D",it["ITEM_CODE"],"19950103",YMD))
    if not pairs:
        pairs = rows_to_pairs(ecos_series("802Y001","D",it["ITEM_CODE"],"20200102",YMD))
    if not pairs: raise RuntimeError(f"市值序列为空(项目:{it.get('ITEM_NAME')} 代码:{it.get('ITEM_CODE')})")
    sc = calibrate("mcap", pairs[-1][1], it.get("UNIT_NAME"))
    if sc is None: raise RuntimeError(f"市值数量级异常: 原始最新值={pairs[-1][1]} 单位={it.get('UNIT_NAME')}")
    d=[p[0] for p in pairs]; v=[round(p[1]*sc,1) for p in pairs]
    print(f"  ✓ {len(d)}个交易日 ({d[0]} ~ {d[-1]}), 最新 {v[-1]:,.0f} 万亿 (原始单位:{it.get('UNIT_NAME')})")
    return {"d":d,"v":v,"f":"D","src":f"ECOS 802Y001·{it.get('ITEM_NAME','')}"}

def fetch_deposits():
    out={}
    items = ecos_items("104Y015")
    for key, kw, label in (("demand","요구불","活期存款"),("time","저축성","定期/储蓄性存款")):
        print(f"· {label}(月频, ECOS 104Y015)…", flush=True)
        cands=[r for r in items if kw in (r.get("ITEM_NAME") or "")]
        cands.sort(key=lambda r: len(r.get("ITEM_NAME") or ""))
        if not cands:
            print(f"  ✗ 未找到「{kw}」· 该表项目清单:", [r.get("ITEM_NAME") for r in items][:30]); continue
        it=cands[0]
        pairs=rows_to_pairs(ecos_series("104Y015","M",it["ITEM_CODE"],"199001",YM))
        if not pairs: print(f"  ✗ {label}空序列"); continue
        sc=calibrate(key, pairs[-1][1], it.get("UNIT_NAME"))
        if sc is None: print(f"  ✗ {label}数量级异常 原始={pairs[-1][1]} 单位={it.get('UNIT_NAME')}"); continue
        d=[p[0] for p in pairs]; v=[round(p[1]*sc,2) for p in pairs]
        print(f"  ✓ {len(d)}个月 ({d[0]} ~ {d[-1]}), 最新 {v[-1]:,.1f} 万亿 · 项目:{it.get('ITEM_NAME')}")
        out[key]={"d":d,"v":v,"f":"M","src":f"ECOS 104Y015·{it.get('ITEM_NAME','')}"}
    return out

def fetch_funds_ecos():
    print("· 协会资金面(月频回退, ECOS 901Y056)…", flush=True)
    kwmap={"yetak":["예탁금"],"yungja":["신용융자","신용거래융자"],"rp":["환매조건부","RP"],"misu":["미수금"],"cma":["CMA"]}
    out={}
    items = ecos_items("901Y056")
    if items:
        dbg("901Y056清单: "+", ".join((r.get("ITEM_NAME") or "?") for r in items[:25]))
        groups = {}
        for r in items:
            nm = r.get("ITEM_NAME") or ""
            try:
                pairs = rows_to_pairs(ecos_series("901Y056","M",r["ITEM_CODE"],"197501",YM))
            except Exception:
                continue
            if pairs: groups[nm] = (pairs, r.get("UNIT_NAME"))
    else:
        dbg("901Y056项目清单为空 → 整表兜底抓取")
        rows = ecos_series_all("901Y056","M","197501",YM)
        dbg(f"整表返回 {len(rows)} 行, 项目: "+", ".join(sorted({r.get('ITEM_NAME1') or '?' for r in rows})[:25]))
        groups = {}
        for r in rows:
            nm = r.get("ITEM_NAME1") or "?"
            groups.setdefault(nm, ([], r.get("UNIT_NAME")))
        tmp = {nm:{} for nm in groups}
        for r in rows:
            nm = r.get("ITEM_NAME1") or "?"
            t, v = r.get("TIME",""), r.get("DATA_VALUE")
            try: v=float(v)
            except (TypeError,ValueError): continue
            if len(t)>=6: tmp[nm][f"{t[:4]}-{t[4:6]}"] = v
        groups = {nm:(sorted(tmp[nm].items()), groups[nm][1]) for nm in groups if tmp[nm]}
    for key,kws in kwmap.items():
        hit = next((nm for nm in groups if any(k in nm for k in kws)), None)
        if not hit: dbg(f"funds:{key} 关键词未匹配"); continue
        pairs, unit = groups[hit]
        sc = calibrate(key, pairs[-1][1], unit)
        if sc is None: dbg(f"funds:{key} 数量级异常 原始={pairs[-1][1]} 单位={unit}"); continue
        d=[p[0] for p in pairs]; v=[round(p[1]*sc,2) for p in pairs]
        out[key]={"d":d,"v":v,"f":"M","src":f"ECOS 901Y056·{hit}"}
        print(f"  ✓ {key}: {len(d)}月 ({d[0]}~{d[-1]}), 最新 {v[-1]:,.1f} 万亿 · {hit}")
    return out


def fetch_hhloan():
    print("· 家庭贷款(BOK月度, ECOS 151Y002 예금취급기관 가계대출)…", flush=True)
    rows = [r for r in ecos_series_all("151Y002","M","200001",YM) if "예금은행" in (r.get("ITEM_NAME1") or "")]
    if not rows: dbg("151Y002 整表无예금은행行"); return {}
    groups={}
    for r in rows:
        nm = (r.get("ITEM_NAME2") or r.get("ITEM_NAME1") or "합계").strip()
        t, v = r.get("TIME",""), r.get("DATA_VALUE")
        try: v=float(v)
        except (TypeError,ValueError): continue
        if len(t)>=6: groups.setdefault(nm,{})[f"{t[:4]}-{t[4:6]}"]=(v, r.get("UNIT_NAME"))
    if not groups: dbg("151Y002 分组为空"); return {}
    # 选最新值最大的组 = 家庭贷款总额(总额>住房抵押>其他)
    best=None
    for nm,mp in groups.items():
        last_ym=max(mp); lv=mp[last_ym][0]
        dbg(f"151Y002 예금은행·{nm}: 最新原始值={lv}")
        if best is None or lv>best[2]: best=(nm,mp,lv)
    nm,mp,_=best
    pairs=sorted((k,v[0]) for k,v in mp.items()); unit=next(iter(mp.values()))[1]
    sc=calibrate("hhloan", pairs[-1][1], unit)
    if sc is None: dbg(f"家庭贷款数量级异常 原始={pairs[-1][1]} 单位={unit}"); return {}
    d=[p[0] for p in pairs]; v=[round(p[1]*sc,1) for p in pairs]
    print(f"  ✓ {len(d)}个月 ({d[0]}~{d[-1]}), 最新 {v[-1]:,.1f} 万亿 · 예금은행·{nm}")
    return {"hhloan":{"d":d,"v":v,"f":"M","src":"ECOS 151Y002·예금은행 가계대출(말잔)"}}

# ---------------------------- data.go.kr 协会日频 ----------------------------
G = "https://apis.data.go.kr/1160100/service/GetKofiaStatisticsInfoService"
OP_CANDS = {  # 官方Swagger确认的真实操作名
  "fund":  ["getSecuritiesMarketTotalCapitalInfo"],   # 증시자금추이(日频): 预托金/RP/垫付欠款
  "credit":["getGrantingOfCreditBalanceInfo"],        # 신용공여잔고추이(日频): 融资/质押
  "cma":   ["getCMAStatus"],                          # 일자별CMA현황(日频)
}
def gk(op, page=1, rows=5000):
    r = requests.get(f"{G}/{op}", params={"serviceKey":DATA_GO_KR_KEY,"pageNo":page,
        "numOfRows":rows,"resultType":"json"}, timeout=90)
    if r.status_code!=200: raise RuntimeError(f"HTTP{r.status_code} {r.text[:80]}")
    try: j=r.json()
    except ValueError: raise RuntimeError("非JSON:"+r.text[:100])
    hd=j.get("response",{}).get("header",{})
    if hd.get("resultCode") not in ("00","0"): raise RuntimeError(hd.get("resultMsg","err"))
    body=j["response"]["body"]
    return body.get("items",{}).get("item",[]), int(body.get("totalCount",0))

def probe(group):
    for op in OP_CANDS[group]:
        try:
            items,total=gk(op,1,2)
            if total>0:
                dbg(f"探测成功 {group}:{op} 共{total}行 字段={list(items[0].keys()) if items else '?'}")
                return op,total
            dbg(f"{group}:{op} total=0")
        except Exception as e:
            dbg(f"{group}:{op} {str(e)[:80]}")
    return None,0

def key_check():
    """用官方文档公开的操作①验证 data.go.kr 钥匙+服务名是否有效"""
    try:
        items,total=gk("getTrustScaleInfo",1,2)
        dbg(f"钥匙验证: getTrustScaleInfo 可用, total={total} → 钥匙/服务名OK, 若其他op失败则为操作名问题")
        return True
    except Exception as e:
        dbg(f"钥匙验证失败: {str(e)[:120]} → 钥匙未生效或服务地址问题")
        return False

def date_field(item):
    for k,v in item.items():
        s=str(v)
        if len(s)==8 and s.isdigit() and s.startswith(("19","20")): return k
    return None

def pull_all(op,total):
    items=[]; page=1
    while len(items)<total:
        chunk,_=gk(op,page,10000); items+=chunk; page+=1
        if page>50: break
        time.sleep(0.3)
    return items

def series_from_items(items, val_kws, anchor_key):
    """val_kws: 字段名关键词(小写); 用锚点自动定标"""
    if not items: return None
    df=date_field(items[0])
    if not df: return None
    fld=None
    for k in items[0].keys():
        lk=k.lower()
        if any(w in lk for w in val_kws): fld=k; break
    if not fld:
        dbg(f"字段嗅探失败({anchor_key}): 可用字段={list(items[0].keys())}"); return None
    tmp={}
    for it in items:
        s=str(it.get(df,"")); 
        try: v=float(str(it.get(fld,"")).replace(",",""))
        except ValueError: continue
        if len(s)==8: tmp[f"{s[:4]}-{s[4:6]}-{s[6:8]}"]=v
    if not tmp: return None
    d=sorted(tmp); v=[tmp[x] for x in d]
    sc=snap_scale(v[-1],ANCHOR.get(anchor_key,100))
    if sc is None: return None
    return {"d":d,"v":[round(x*sc,3) for x in v],"f":"D","src":f"data.go.kr 협회·{fld}"}

def fetch_funds_daily():
    print("· 协会资金面(日频, data.go.kr)…", flush=True)
    out={}
    key_check()
    op,total=probe("fund")
    if op:
        items=pull_all(op,total)
        if items: print(f"  字段样例(증시자금): {list(items[0].keys())}")
        for key,kws in (("yetak",["dpsg","dpst","depo","invst","ivst"]),("rp",["rp","repo"]),
                        ("misu",["ucolmny","ucol","msu","misu"])):
            s=series_from_items(items,kws,key)
            if s: out[key]=s; print(f"  ✓ {key} 日频 {len(s['d'])}点 最新{s['v'][-1]:,.1f}万亿")
        # 强平/垫付比重: 接口原生比率字段(RlImpt), 不做万亿换算
        if items:
            df=date_field(items[0])
            fld=next((k for k in items[0] if "rlimpt" in k.lower()),None)
            if df and fld:
                tmp={}
                for it2 in items:
                    t=str(it2.get(df,""))
                    try: v=float(str(it2.get(fld,"")).replace(",",""))
                    except ValueError: continue
                    if len(t)==8: tmp[f"{t[:4]}-{t[4:6]}-{t[6:8]}"]=v
                if tmp:
                    dd=sorted(tmp); vv=[tmp[x] for x in dd]
                    med=sorted(vv)[len(vv)//2]
                    if med<1: vv=[round(x*100,2) for x in vv]   # 小数比率→百分比
                    if 0.05<sorted(vv)[len(vv)//2]<60:
                        out["forced"]={"d":dd,"v":[round(x,2) for x in vv],"f":"D","src":f"data.go.kr 협회·{fld}"}
                        print(f"  ✓ forced 日频 {len(dd)}点 最新{vv[-1]:.1f}%")
                    else: dbg(f"forced 比率量级异常 中位数={sorted(vv)[len(vv)//2]}")
    op,total=probe("credit")
    if op:
        items=pull_all(op,total)
        if items: print(f"  字段样例(신용공여): {list(items[0].keys())}")
        for key,kws in (("yungja",["fnc","loan","crdt"]),("jiya",["scrt","scty","secu","pledge","mrtg","cltr"])):
            s=series_from_items(items,kws,key)
            if s: out[key]=s; print(f"  ✓ {key} 日频 {len(s['d'])}点 最新{s['v'][-1]:,.1f}万亿")
    op,total=probe("cma")
    if op:
        items=pull_all(op,total)
        if items:
            tgts=sorted({str(it2.get("mngInvTgt","")) for it2 in items})
            ctgs=sorted({str(it2.get("invrCtg","")) for it2 in items})
            dbg(f"CMA维度 운용대상={tgts} 투자자구분={ctgs}")
            tot_tgt=next((t for t in tgts if any(w in t for w in ("합계","전체","계"))),None)
            tot_ctg=next((c for c in ctgs if any(w in c for w in ("합계","전체","계"))),None)
            tmp={}
            for it2 in items:
                t=str(it2.get("basDt",""))
                if len(t)!=8: continue
                if tot_tgt and str(it2.get("mngInvTgt",""))!=tot_tgt: continue
                if tot_ctg and str(it2.get("invrCtg",""))!=tot_ctg: continue
                try: v=float(str(it2.get("actBal","")).replace(",",""))
                except ValueError: continue
                key2=f"{t[:4]}-{t[4:6]}-{t[6:8]}"
                tmp[key2]=tmp.get(key2,0.0)+v
            if tmp:
                dd=sorted(tmp); raw=[tmp[x] for x in dd]
                sc=calibrate("cma",raw[-1],"원")
                if sc:
                    vv=[round(x*sc,2) for x in raw]
                    # 锚点验证: 2026-06月末应≈110.5
                    junes=[i for i,x in enumerate(dd) if x.startswith("2026-06")]
                    ok = (not junes) or abs(vv[junes[-1]]-110.5)/110.5<0.2
                    if ok:
                        out["cma"]={"d":dd,"v":vv,"f":"D","src":"data.go.kr 협회·actBal聚合"}
                        print(f"  ✓ cma 日频 {len(dd)}点 最新{vv[-1]:,.1f}万亿")
                    else: dbg(f"CMA锚点验证失败: 2026-06末={vv[junes[-1]]} vs 底稿110.5")
                else: dbg(f"CMA数量级异常 原始最新={raw[-1]}")
    if not out:
        print("  ✗ 日频探测失败(操作名未命中或密钥未审批)。请打开数据集页面→상세기능(Swagger)查看真实操作名,")
        print("    替换脚本顶部 OP_CANDS 中对应候选列表首位后重跑: https://www.data.go.kr/data/15094809/openapi.do")
    return out

# ---------------------------- 主流程 ----------------------------
def main():
    out={"meta":{"fetched_at":dt.datetime.now().strftime("%Y-%m-%d %H:%M"),"notes":[],"debug":DEBUG}}
    try: out["mcap"]=fetch_mcap()
    except Exception as e: print(f"  ✗ 市值失败: {e}"); out["meta"]["notes"].append(f"mcap失败:{e}")
    try: out.update(fetch_deposits())
    except Exception as e: print(f"  ✗ 存款失败: {e}"); out["meta"]["notes"].append(f"存款失败:{e}")
    try: out.update(fetch_hhloan())
    except Exception as e: print(f"  ✗ 家庭贷款失败: {e}"); out["meta"]["notes"].append(f"家庭贷款失败:{e}")
    funds={}
    if DATA_GO_KR_KEY.strip():
        try: funds=fetch_funds_daily()
        except Exception as e: print(f"  ✗ 日频协会数据失败: {e}")
    try:
        m=fetch_funds_ecos()
        for k,v in m.items():
            if k not in funds: funds[k]=v   # 日频优先, 月频补缺
    except Exception as e: print(f"  ✗ ECOS协会月频失败: {e}")
    out["funds"]=funds

    print("\n========== 序列体检报告 ==========")
    def rep(k,v):
        if v and v.get("d"): print(f"  {k:8s} {v['f']} {len(v['d']):>6}点  {v['d'][0]} ~ {v['d'][-1]}  最新={v['v'][-1]:,}")
        else: print(f"  {k:8s} 缺失")
    rep("mcap",out.get("mcap")); rep("demand",out.get("demand")); rep("time",out.get("time")); rep("hhloan",out.get("hhloan"))
    for k in ("yetak","yungja","jiya","rp","misu","cma","forced"): rep(k,(out.get("funds") or {}).get(k))
    print("==================================\n")
    with open("data.js","w",encoding="utf-8") as f:
        f.write("window.KOREA_DATA=");json.dump(out,f,ensure_ascii=False,separators=(",",":"));f.write(";")
    with open("data_backup.json","w",encoding="utf-8") as f:
        json.dump(out,f,ensure_ascii=False)
    print("\n完成 → 已写入 data.js (与HTML同目录时网页自动加载)")
    print("抽查建议: 打开 freesis.kofia.or.kr 与 ecos.bok.or.kr 各核对1-2个最新值")

if __name__=="__main__":
    main()
