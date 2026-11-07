# 데이터 출처

## 버전 및 다운로드 이력

기준일은 **2024-04-30 KST**, 아래 5개 ZIP의 실제 다운로드일은 **2026-11-07 KST**다. 원본 이름과 로컬 이름을 구분했다. 포털의 데이터셋 공개일은 시리즈 등록일이며 개별 파일 버전 공개일과 구분한다. 개별 파일의 포털 수정일은 파일 내려받기 표에서, ZIP 멤버 날짜와 SHA-256은 확보한 바이트에서 확인했다.

| 원본 파일명 및 다운로드 URL | 로컬 이름 | 관측 기간 또는 공간 시점 | 포털 파일 수정일 | ZIP 멤버 날짜 | 바이트 | SHA-256 |
| --- | --- | --- | --- | --- | ---: | --- |
| [서울시_상권분석서비스(추정매출-상권)_2021년.zip](https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?infId=OA-15572&seq=47&infSeq=3) | `sales-2021.zip` | 2021Q1–Q4 | 2023-10-30 | 2025-06-04 | 14,569,835 | `856e78aaacded902201d2476b274c5eb4f90b86eece4af4e4f2bba60c3d79eed` |
| [서울시_상권분석서비스(추정매출-상권)_2022년.zip](https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?infId=OA-15572&seq=48&infSeq=3) | `sales-2022.zip` | 2022Q1–Q4 | 2023-10-30 | 2025-06-04 | 14,550,635 | `748bf317428f5085ba64aeee9aed6c52b465b304d28c941d527e816d1909abe6` |
| [서울시_상권분석서비스(점포-상권)_2021년.zip](https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?infId=OA-15577&seq=16&infSeq=3) | `stores-2021.zip` | 2021Q1–Q4 | 2023-10-30 | 2025-06-04 | 2,131,800 | `c77313e0faab4fe4fe39a1657f2f530640c945ba41601e9eb960dd32bdc2434b` |
| [서울시_상권분석서비스(점포-상권)_2022년.zip](https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?infId=OA-15577&seq=17&infSeq=3) | `stores-2022.zip` | 2022Q1–Q4 | 2023-10-30 | 2025-06-04 | 2,140,484 | `03ffa708ed864d12b56e8c608eb9d83e5337ff3ed3bd28826db9593fab678930` |
| [서울시 상권분석서비스(영역-상권).zip](https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?infId=OA-15560&seq=5&infSeq=3) | `areas.zip` | 2023년 10월 파일 스냅샷. 경계별 관측 분기는 제공되지 않음 | 2023-10-23 | 2023-10-20 | 2,123,078 | `38bb8fab4e45a1171af4989cd7fa1275f68e5d644aa770f5431ce7ccc38384dd` |

포털 시리즈 공개일은 추정매출 2019-05-29, 점포 2019-06-04, 영역 2019-04-25다. [추정매출 OA-15572](https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do) · [점포 OA-15577](https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do) · [영역 OA-15560](https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do)

- **매출·점포 적격성 보류.** 파일 목록 용량은 매출 12.55/12.96 MB, 점포 4.01/3.9 MB다. 받은 ZIP의 멤버 날짜가 기준일 이후이고 용량도 목록과 다르다. 타임스탬프만으로 데이터 값의 변경 여부까지 판단할 수 없다. 기준일 당시 파일과의 동일성을 입증할 해시·보관본은 확보하지 못했다. 2026년 제공기간 공지는 과거 기간 데이터에도 표준단위구역 기준의 매출 제공이 적용됐음을 설명한다. 이 공지는 현재 배포판을 조사하는 데만 사용했다. [서울 열린데이터광장 제공기간 공지](https://data.seoul.go.kr/together/notice/datasetNoticeView.do?bbsCd=10008&ditcCd=&pageIndex=1&seq=a2197dabd5a3a52edd6fe0d4eead6bd3)
- **길단위인구 미확보.** OA-15568 상세 페이지는 접근 시 서비스 종료 안내를 반환했다. 기준일 이전 공개·수정 근거가 있는 해당 상권 단위 보관 ZIP을 확보하지 못했다. 파일명, 다운로드일, 해시는 미확인 상태다. [길단위인구 OA-15568](https://data.seoul.go.kr/dataList/OA-15568/S/1/datasetView.do)
- **2023년 확장 미실행.** 현재 포털의 2023년 추정매출·점포 파일 목록 수정일은 각각 2025-01-13이다. 적격한 별도 파일과 코드·컬럼 호환성 근거를 확인하지 못해 다운로드 및 분석을 생략했다.

## 수동 다운로드와 보관본 사용

1. 서울 열린데이터광장의 각 시리즈 상세 → **파일내려받기** → 위 표의 원본 이름을 선택한다. 받은 ZIP을 풀지 않고 `data/raw/`에 넣고, 위 표의 로컬 이름을 사용한다. 이 경로에서는 포털 현재 버전을 검수할 수 있다.
2. 기준일 이전에 게시된 버전이 필요한 경우, 위 연도·종류 4개에 대응하는 당시 보관 ZIP 또는 CSV를 확보한다. 게시일을 확인할 수 있는 아카이브 스냅샷이나 제공기관 확인과 함께 파일별 출처 URL, 공개·수정일 근거, 다운로드일, SHA-256을 추가 기록한다. 현재 포털 파일명과 수정일만으로 적격성을 지정하면 안 된다.
3. `docs/inputs.json`을 `data/archive_inputs.json`으로 복사한다. 해당 키마다 보관본의 `path`(raw 디렉터리 기준), `sha256`, `version_date`(YYYY-MM-DD), `version_evidence`(버전 근거 URL 또는 식별자)를 기록하고, 현행 자동 다운로드용 `seq`를 제거한다. 매출에는 당시 정의에 맞는 `sales_unit`도 지정한다. `분기당 매출 금액`이면 `quarter_total`, 분기 내 월평균이라고 자료 정의에서 확인한 `당월 매출 금액`이면 `monthly_average`다. 해시가 다르거나 ZIP 내부에 기준일 이후 날짜가 있으면 실행에서 제외된다.
4. 검증된 인구 보관본을 쓰려면 같은 방법으로 `population-2022` 등 관측 연도에 맞는 키를 넣는다. 사용 분기의 상권 코드가 유일하고 공간 수요점 전체에 유효 가중치가 결합될 때 사용한다.

## 출처 표시와 공유 범위

원천 자료는 서울특별시 저작물이며, 서울 열린데이터광장의 추정매출·점포·영역 상세 페이지는 공공누리 제1유형을 표시한다. 저장소의 공간 지도는 서울특별시 영역-상권(OA-15560)의 2023년 10월 버전을 가공한 것으로, 이미지에 출처를 표시했다. 공개 포털 원본 ZIP·CSV는 로컬에 보관한다. 분석이 실행되면 파생 예측·후보 CSV를 공유하기 전에 사용한 보관본과 수요 자료의 이용 조건을 다시 확인한다. [공공누리 제1유형](https://www.kogl.or.kr/info/licenseType1.do)

## 방법과 실행 환경

- 최대 커버리지 입지 문제는 Church & ReVelle(1974)의 MCLP를 사용했다. [논문](https://doi.org/10.1111/j.1435-5597.1974.tb00902.x)
- Ridge와 랜덤 포리스트는 scikit-learn 1.4.2(2024-04-09), 이진 최적화는 SciPy 1.13.0(2024-04-02), 표 처리는 pandas 2.2.2(2024-04-10)를 사용한다. 전이 의존성까지 `requirements.txt`에서 버전을 고정했다. [scikit-learn](https://pypi.org/project/scikit-learn/1.4.2/) · [SciPy](https://pypi.org/project/scipy/1.13.0/) · [pandas](https://pypi.org/project/pandas/2.2.2/)
