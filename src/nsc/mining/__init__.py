"""规则挖掘（T-14/T-15）。L0 observation → L1 candidate → L2 → L3。

晋升门槛见 spec/rules/PROMOTION.md。本包只做编排与确定性聚类；
归纳（RuleInduce）是语义判定，prompt 契约在 spec/passes/signatures.py::RuleInduce。
"""
