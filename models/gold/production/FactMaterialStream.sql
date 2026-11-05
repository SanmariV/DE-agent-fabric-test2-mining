with

material_stream as (

    select * from {{ ref('production.MaterialStream') }}

),

facility as (

    select * from {{ ref('facilities.DimFacility') }}

),

material as (

    select * from {{ ref('production.DimMaterial') }}

),

data_source as (

    select * from {{ ref('facilities.DimDataSource') }}

)

select
    material_stream.MaterialStream_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    coalesce(material.DimMaterial_SK, -1) as DimMaterial_SK,
    coalesce(data_source.DimDataSource_SK, -1) as DimDataSource_SK,
    material_stream.StreamSourceCode,
    material_stream.StreamTypeCode,
    material_stream.ReportingPeriod,
    material_stream.ReportingYear,
    material_stream.ValueTonnes,
    material_stream.AmountSoldTonnes
from material_stream
left join facility
    on facility.Facility_BK = material_stream.Facility_BK
left join material
    on material.Material_BK = material_stream.Material_BK
left join data_source
    on data_source.DataSource_BK = material_stream.DataSource_BK
