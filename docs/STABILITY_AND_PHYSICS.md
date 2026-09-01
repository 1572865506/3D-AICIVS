# Physics and Stability

## SupportGraph

Nodes:
cargo/floor

Edges:
- overlap/contact area
- load ratio
- support ratio
- contact direction
- lateral constraint

## Compression

Upper weight is distributed by actual support/contact contribution.

Never model compression solely by "number of boxes on top".

## Stability levels

### Item Stability
- support ratio
- COM projection
- overhang
- edge margin
- slenderness

### Cluster Stability
- connected cargo group
- combined COM
- shared support region
- lateral interlock

### Wall Stability
- wall base polygon
- total COM
- height/thickness ratio
- wall/neighbor contact
- tipping risk

## Stability states
- SELF_STABLE
- CONDITIONALLY_STABLE
- SUPPORTED_STABLE
- WARNING
- UNSTABLE

## Stability Debt
A conditionally stable item may be committed only under a bounded temporary-debt policy.
Debt must resolve before wall/phase/final close.
