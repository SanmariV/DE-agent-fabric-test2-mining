with mineral as (
    select * from {{ ref('dbo.MineralProduction') }}
),

coal as (
    select * from {{ ref('dbo.CoalProduction') }}
),

mineral_stream as (
    select
        concat('MINERAL-', cast(mineral.MineralProduction_BK as string)) as MaterialStream_BK,
        'MINERAL' as StreamSourceCode,
        mineral.Facility_BK,
        mineral.Material_BK,
        mineral.DataSource_BK,
        mineral.StreamTypeCode,
        mineral.ReportingPeriod,
        mineral.ReportingYear,
        mineral.ValueTonnes,
        mineral.AmountSoldTonnes
    from mineral
),

coal_stream as (
    select
        concat('COAL-', cast(coal.CoalProduction_BK as string)) as MaterialStream_BK,
        'COAL' as StreamSourceCode,
        coal.Facility_BK,
        coal.Material_BK,
        coal.DataSource_BK,
        upper(coal.StreamType) as StreamTypeCode,
        coal.ReportingPeriod,
        coal.ReportingYear,
        coal.ValueTonnes,
        coal.AmountSoldTonnes
    from coal
)

select * from mineral_stream
union all
select * from coal_stream
