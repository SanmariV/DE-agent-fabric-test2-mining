with mineral as (
    select * from {{ ref('dbo.MineralProduction') }}
),

waste as (
    select * from {{ ref('dbo.WasteStream') }}
),

facility_year as (
    select
        mineral.Facility_BK,
        mineral.ReportingYear
    from mineral
    union
    select
        waste.Facility_BK,
        waste.ReportingYear
    from waste
),

mineral_total as (
    select
        mineral.Facility_BK,
        mineral.ReportingYear,
        sum(case when mineral.StreamTypeCode = 'ORE MINED' then mineral.ValueTonnes end) as OreMinedTonnes,
        sum(case when mineral.StreamTypeCode = 'ORE PROCESSED' then mineral.ValueTonnes end) as OreProcessedTonnes,
        sum(case when mineral.StreamTypeCode = 'CONCENTRATE' then mineral.ValueTonnes end) as ConcentrateTonnes
    from mineral
    group by
        mineral.Facility_BK,
        mineral.ReportingYear
),

waste_total as (
    select
        waste.Facility_BK,
        waste.ReportingYear,
        sum(waste.ValueTonnes) as WasteTonnes
    from waste
    group by
        waste.Facility_BK,
        waste.ReportingYear
)

select
    concat(facility_year.Facility_BK, '-', cast(facility_year.ReportingYear as string)) as FacilityYear_BK,
    facility_year.Facility_BK,
    facility_year.ReportingYear,
    mineral_total.OreMinedTonnes,
    mineral_total.OreProcessedTonnes,
    mineral_total.ConcentrateTonnes,
    waste_total.WasteTonnes
from facility_year
left join mineral_total
    on mineral_total.Facility_BK = facility_year.Facility_BK
    and mineral_total.ReportingYear = facility_year.ReportingYear
left join waste_total
    on waste_total.Facility_BK = facility_year.Facility_BK
    and waste_total.ReportingYear = facility_year.ReportingYear
