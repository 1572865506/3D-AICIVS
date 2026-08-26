class AboveCargoAdmissionResolver:
    """Resolve mixed-SKU cargo above a carton without abusing self stack limit."""
    def resolve(self, lower_sku, upper_sku, top_load_kg, support_ratio):
        policy=lower_sku.stacking_policy
        if not policy.allow_stacking_on_top:return False,"ABOVE_CARGO_FORBIDDEN"
        if policy.allowed_above_categories and upper_sku.cargo_class not in policy.allowed_above_categories:
            return False,"ABOVE_CARGO_FORBIDDEN"
        if upper_sku.cargo_class in policy.forbidden_above_categories:
            return False,"ABOVE_CARGO_FORBIDDEN"
        required=max(policy.min_support_ratio,upper_sku.stacking_policy.min_support_ratio)
        if support_ratio+1e-9<required:return False,"SUPPORT_FAIL"
        limits=[x for x in (policy.max_bearing_kg,
            lower_sku.cargo_profile.compression_policy.max_top_load_kg if lower_sku.cargo_profile else None) if x is not None]
        if limits and top_load_kg>min(limits)+1e-9:return False,"COMPRESSION_FAIL"
        # max_stack_layers intentionally does not participate here. It governs
        # a contiguous stack of lower_sku only and is validated independently.
        return True,"AUTO_PASS"
