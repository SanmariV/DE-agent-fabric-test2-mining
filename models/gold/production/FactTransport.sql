with

transport as (

    select * from {{ ref('dbo.TransportFlow') }}

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
    transport.TransportFlow_BK,
    coalesce(facility.DimFacility_SK, -1) as DimFacility_SK,
    coalesce(material.DimMaterial_SK, -1) as DimMaterial_SK,
    coalesce(data_source.DimDataSource_SK, -1) as DimDataSource_SK,
    transport.TransportTo,
    transport.TransportBy,
    transport.ExportTo,
    transport.ReportingPeriod,
    transport.IsExport,
    transport.ReportingYear,
    transport.ValueTonnes
from transport
left join facility
    on facility.Facility_BK = transport.Facility_BK
left join material
    on material.Material_BK = transport.Material_BK
left join data_source
    on data_source.DataSource_BK = transport.DataSource_BK
