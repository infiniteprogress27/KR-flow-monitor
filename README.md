# 韩国股市资金面·杠杆监测台

十一项指标 · 总额/YoY/占KOSPI市值 · 每交易日自动更新

## 部署(一次性, 全程网页操作)
1. 新建GitHub仓库(Public), 名字任意
2. 上传本文件夹全部内容(含 .github 目录; 网页上传如无法传文件夹, 用"Add file→Create new file"输入路径 `.github/workflows/update.yml` 粘贴内容)
3. Settings → Secrets and variables → Actions → New repository secret:
   - `ECOS_KEY` = 韩国银行ECOS密钥
   - `DATA_GO_KR_KEY` = 公共数据门户密钥(可选; 填了协会七序列升级为日频)
4. Actions 标签页 → auto-update-data → Run workflow (手动触发首跑, 生成 data.js)
5. Settings → Pages → Source: Deploy from a branch → main / root → Save
6. 访问 `https://<用户名>.github.io/<仓库名>/`

## 日常
无需操作。每交易日 09:30 (韩国时间) 自动更新。
