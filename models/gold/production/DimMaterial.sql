select
    material.Material_BK,
    material.MaterialName,
    material.MaterialCategoryCode,
    material.MaterialSecondaryCategory,
    material.AggregateMaterial_BK,
    material.AggregateMaterialName,
    material.MaterialsContained
from {{ ref('dbo.Material') }} as material
