# Top Fill Tests

Display-like carton:
0.553 × 0.080 × 0.355

Scenarios:
1. main body has room for upright -> flat orientation should not be preferred
2. top gap < upright height but >= flat thickness -> conditional flat may be legal
3. insufficient support -> reject
4. excessive unsupported span -> reject
5. lower cargo compression exceeded -> reject
6. flat layer count exceeded -> reject
7. all conditions pass -> accept
