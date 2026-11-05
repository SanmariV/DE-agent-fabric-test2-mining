with commodity as (
    select * from {{ ref('dbo.CommodityProduction') }}
),

mineral as (
    select * from {{ ref('dbo.MineralProduction') }}
)

select
    commodity.CommodityProduction_BK,
    commodity.Facility_BK,
    commodity.Material_BK,
    commodity.CommodityMaterial_BK,
    commodity.MineralProduction_BK,
    commodity.DataSource_BK,
    mineral.StreamTypeCode,
    commodity.ReportingPeriod,
    commodity.ReportingYear,
    commodity.ValueTonnes,
    commodity.GradePartsPerMillion,
    commodity.RecoveryRate,
    commodity.YieldPartsPerMillion,
    commodity.AmountSoldTonnes,
    commodity.MetalPayableTonnes,
    mineral.ValueTonnes as MineralValueTonnes,
    mineral.OverallGradePartsPerMillion as MineralOverallGradePartsPerMillion
from commodity
left join mineral
    on mineral.MineralProduction_BK = commodity.MineralProduction_BK
