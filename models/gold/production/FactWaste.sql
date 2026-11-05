with

waste as (

    select * from {{ ref('dbo.WasteStream') }}

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
    waste.WasteStream_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    coalesce(material.DimMaterial_SK, -1) as DimMaterial_SK,
    coalesce(commodity_material.DimMaterial_SK, -1) as CommodityDimMaterial_SK,
    coalesce(data_source.DimDataSource_SK, -1) as DimDataSource_SK,
    waste.MiningMethodCode,
    waste.WasteType,
    waste.ReportingPeriod,
    waste.ReportingYear,
    waste.ValueTonnes,
    waste.TotalMaterialTonnes,
    waste.StrippingRatio
from waste
left join facility
    on facility.Facility_BK = waste.Facility_BK
left join material
    on material.Material_BK = waste.Material_BK
left join commodity_material
    on commodity_material.Material_BK = waste.CommodityMaterial_BK
left join data_source
    on data_source.DataSource_BK = waste.DataSource_BK
