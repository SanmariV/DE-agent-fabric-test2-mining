with

commodity_output as (

    select * from {{ ref('production.CommodityOutput') }}

),

facility as (

    select * from {{ ref('facilities.DimFacility') }}

),

material as (

    select * from {{ ref('production.DimMaterial') }}

),

commodity_material as (

    select * from {{ ref('production.DimMaterial') }}

),

data_source as (

    select * from {{ ref('facilities.DimDataSource') }}

)

select
    commodity_output.CommodityProduction_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    coalesce(material.DimMaterial_SK, -1) as DimMaterial_SK,
    coalesce(commodity_material.DimMaterial_SK, -1) as CommodityDimMaterial_SK,
    coalesce(data_source.DimDataSource_SK, -1) as DimDataSource_SK,
    commodity_output.StreamTypeCode,
    commodity_output.ReportingPeriod,
    commodity_output.ReportingYear,
    commodity_output.ValueTonnes,
    commodity_output.GradePartsPerMillion,
    commodity_output.RecoveryRate,
    commodity_output.YieldPartsPerMillion,
    commodity_output.AmountSoldTonnes,
    commodity_output.MetalPayableTonnes
from commodity_output
left join facility
    on facility.Facility_BK = commodity_output.Facility_BK
left join material
    on material.Material_BK = commodity_output.Material_BK
left join commodity_material
    on commodity_material.Material_BK = commodity_output.CommodityMaterial_BK
left join data_source
    on data_source.DataSource_BK = commodity_output.DataSource_BK
