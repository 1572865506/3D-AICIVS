# Orientation + Top Fill

Orientation is context-dependent.

## Example display carton

Main body:
- upright only/preferred

Wall:
- upright only/preferred

Top fill:
- allowed flat face may be enabled conditionally

## Conditional flat placement requires

- context == TOP_FILL
- primary upright orientation cannot reasonably fit target top space
- configured flat orientation is permitted
- support ratio >= SKU threshold
- unsupported span <= SKU threshold
- lower cargo compression is safe
- flat stack layer <= configured maximum
- flat orientation's own top-load rule passes
- stability passes

## Orientation scoring

Preferred upright:
penalty 0

Conditional flat:
non-zero penalty

Therefore solver will not flatten all displays merely to improve utilization.

## TopFillBlock

Top-fill may aggregate repeated identical cartons into compact layer blocks to reduce search complexity.
