# 研究來源與模型邊界

核對日期：2026-10-19。以下使用原始論文、OpenGATE 官方程式／文件與 Geant4 官方文件。

1. [Korcyl 等：Evaluation of Single-Chip, Real-Time Tomographic Data Processing on FPGA – SoC Devices](https://arxiv.org/pdf/1807.10754)，2018。圖 1 將 ROR 定義為 TOF 資訊定位的 LOR 區段；第 III.D 節計算各候選配對的空間座標，第 III.E 節累積二維直方圖與三維點雲。本專案以 ROR 中心點累積作為 Python 驗證基礎，CTR 則用於說明定位的不確定度；目前尚未實作有限寬度核函數累積，也未複製論文的 FPGA/TDC 解析與雙端塑膠閃爍條讀出。
2. [OpenGATE 官方安裝文件](https://opengate-python.readthedocs.io/en/master/user_guide/user_guide_installation.html) 建議隔離 Python 環境，首次執行會下載 Geant4 物理資料。安裝情況以實際執行紀錄為準。[opengate-core 10.1.1 發布檔案](https://pypi.org/project/opengate-core/10.1.1/#files) 明列 CPython 3.11 的 Windows x86-64 wheel，因此本機優先使用 Windows Conda，不預設必須使用 WSL。
3. [官方 test037 PET Hits/Singles 範例](https://github.com/OpenGATE/opengate/blob/master/opengate/tests/src/actors/test037_pet_hits_singles_helpers.py) 示範 `DigitizerHitsCollectionActor → DigitizerAdderActor`，並列出 `GlobalTime`、`TotalEnergyDeposit`、`PostPosition_X/Y/Z`。同一程式比較新舊版本時，將 GATE 10 的 `GlobalTime` 乘 `1e-9`；這支持 GATE 10 ROOT 為 ns，舊 GATE 的 `time` 為 s。不能對兩者套用相同時間倍率。
4. [官方 test072 PET coincidence 資料生成案例](https://github.com/OpenGATE/opengate/blob/master/opengate/tests/src/actors/test072_coinc_sorter_step1.py) 提供環狀晶體、BGO 化學計量密度、背對背 511 keV 光子與未配對 Singles 的 Python API。[背對背光源官方測試](https://github.com/OpenGATE/opengate/blob/master/opengate/tests/src/source/test072_back_to_back_source.py) 驗證每個事件的兩個光子能量與反向性。本專案的幾何尺寸、來源座標與活動度是自行設定的簡化研究案例，並非臨床掃描儀的校準模型。
5. [OpenGATE Actors：Coincidence Sorter](https://opengate-python.readthedocs.io/en/master/user_guide/user_guide_reference_actors.html#coincidence-sorter) 定義 `window` 為兩個 Singles 可配對的最大時間差。`multi_window=True` 會由每個 Single 開窗；`TakeAllGoods` 保留所有符合條件的配對，`RemoveMultiples` 則拒絕多重事件。研究必須明確報告多重事件政策；不同開窗及多重事件政策可能得到不同事件數。
6. [Geant4：System of units](https://geant4.web.cern.ch/documentation/pipelines/master/bfad_html/ForApplicationDevelopers/Fundamentals/unitSystem.html) 的內部基礎單位為 mm、ns、MeV。本專案標準化為 mm、ps、keV，GATE 10 ROOT 讀取時分別乘 `1`、`1000`、`1000`。外部資料應指定自己的欄位及單位，不可僅憑副檔名推測。
7. [Fisher Information-Based Evaluation of Image Quality for Time-of-Flight PET](https://pmc.ncbi.nlm.nih.gov/articles/PMC2828326/) 說明 Gaussian TOF kernel 的空間 FWHM 為 `c × CTR / 2`。若 CTR 是兩個時間戳差值的 FWHM，而兩端誤差獨立且相同，單端 FWHM 應為 `CTR / sqrt(2)`；不能將 CTR 直接作為每一端的 FWHM。
8. [OpenGATE GateVSource 原始碼](https://github.com/OpenGATE/opengate/blob/master/core/opengate_core/opengate_lib/GateVSource.cpp) 的 `CalcNextTime` 在活動度模式下使用指數到達間隔；固定 `number_of_primaries` 模式不增加事件生成時間。因此生成可用於 coincidence 搜尋的連續資料時，本專案採用活動度與模擬時長，不將固定事件數模式的同時刻事件誤當真實事件流。
9. [Geant4 v11.4.0 官方資料集版本與校驗碼](https://github.com/Geant4/geant4/blob/v11.4.0/cmake/Modules/G4DatasetDefinitions.cmake) 列出 `G4NDL 4.7.1` 的 MD5 為 `54f0ed3995856f02433d42ec96d70bc6`。本次初始安裝從 CERN 下載所有 12 份 OpenGATE 必要物理資料；其中 NDL 採 HTTP Range 續傳，完整 archive 的 MD5 與官方定義完全相同後，才交由官方 helper 解壓。本機 Windows Conda 的 OpenGATE 10.1.1 已成功執行 3,000 次期望事件的 smoke 案例，實際產生 2,971 個來源事件與 1,130 筆未配對 Singles；正式結果另見專案報告。

## TOF 正負號約定

本專案明確定義 `u = (p2 − p1) / ||p2 − p1||`，以及 `Δt = t2 − t1`。由兩光子的飛行距離可得 ROR 中心 `m − c × Δt / 2 × u`，其中 `m = (p1 + p2) / 2`。這個正負號來自本專案的方向定義，不是所有文獻都使用相同的 `Δt` 定義。來源靠近 p2 時，t2 較早、Δt 為負，中心沿 u 往 p2 移動；交換兩端標號應得到相同的空間座標。非中心點測試與端點互換測試可防止將時間差正負號寫反。

## 目前可以與不能主張的結果

演算法與理想幾何測試可以驗證單位、排序、配對政策、真值評估與 TOF 計算。OpenGATE 案例另外加入真正的電磁交互作用與晶體內散射，仍使用簡化幾何及時間誤差；不代表已達到完整 PET 定量影像重建。ROR 累積影像尚未包含衰減、散射、隨機、正規化、死時間等完整校正，也不能以中心點誤差取代臨床影像品質驗證。
