use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::{
    BindingId, BindingSetId, ContextId, DefId, DefinitionEffectSetId, DefinitionKind, FileId,
    FlowUncertaintySetId, InternalCandidateId, LoopId, ModuleId, OverloadGroupId, ReferenceId,
    ScopeId, SymbolId, TextRange,
};

#[derive(Clone, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
pub struct SemanticGraph {
    pub modules: Vec<SemanticModule>,
    pub scopes: Vec<ScopeFact>,
    pub contexts: Vec<ContextFact>,
    pub symbols: Vec<SymbolFact>,
    pub bindings: Vec<BindingFact>,
    pub binding_sets: Vec<BindingSetFact>,
    pub flow_uncertainty_sets: Vec<FlowUncertaintySetFact>,
    pub definitions: Vec<SemanticDefinition>,
    pub references: Vec<ReferenceFact>,
    pub context_flow_statuses: Vec<ContextFlowStatusFact>,
    pub definition_effect_sets: Vec<DefinitionEffectSetFact>,
    pub overload_groups: Vec<OverloadGroupFact>,
    pub internal_candidates: Vec<InternalCandidateFact>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SemanticModule {
    pub id: ModuleId,
    pub file: FileId,
    pub name: String,
    pub path: String,
    pub future_annotations: bool,
    pub origin_domain: OriginDomain,
    pub origin_evidence: OriginEvidence,
    pub scope: ScopeId,
    pub context: ContextId,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ScopeFact {
    pub id: ScopeId,
    pub module: ModuleId,
    pub kind: ScopeKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent: Option<ScopeId>,
    pub context: ContextId,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub owner_definition: Option<DefId>,
    pub name: String,
    pub range: TextRange,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ScopeKind {
    Module,
    Function,
    Class,
    Lambda,
    Comprehension,
    Annotation,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ContextFact {
    pub id: ContextId,
    pub module: ModuleId,
    pub kind: ContextKind,
    pub scope: ScopeId,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent: Option<ContextId>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub owner_definition: Option<DefId>,
    pub range: TextRange,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ContextKind {
    ModuleBody,
    FunctionBody,
    ClassBody,
    LambdaBody,
    ComprehensionBody,
    Annotation,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SymbolFact {
    pub id: SymbolId,
    pub module: ModuleId,
    pub scope: ScopeId,
    pub name: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct BindingFact {
    pub id: BindingId,
    pub module: ModuleId,
    pub scope: ScopeId,
    pub symbol: SymbolId,
    pub kind: BindingKind,
    pub name: String,
    pub order: u32,
    pub range: TextRange,
    pub name_range: TextRange,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub definition: Option<DefId>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replaces: Option<BindingId>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct BindingSetFact {
    pub id: BindingSetId,
    pub bindings: Vec<BindingId>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BindingKind {
    Parameter,
    FunctionDefinition,
    ClassDefinition,
    Assignment,
    AnnotatedAssignment,
    AugmentedAssignment,
    Import,
    ImportFrom,
    TypeAlias,
    Delete,
    ForTarget,
    WithTarget,
    ExceptTarget,
    MatchCapture,
    NamedExpression,
    TypeParameter,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SemanticDefinition {
    pub id: DefId,
    pub module: ModuleId,
    pub binding: BindingId,
    pub scope: ScopeId,
    pub context: ContextId,
    pub kind: DefinitionKind,
    pub name: String,
    pub qualified_name: String,
    pub range: TextRange,
    pub name_range: TextRange,
    pub reportable: bool,
    pub is_async: bool,
    pub role: DefinitionRole,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub overload_group: Option<OverloadGroupId>,
    pub definition_effects: DefinitionEffectSetId,
    pub removal_risk: RemovalRisk,
    pub origin_domain: OriginDomain,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ReferenceFact {
    pub id: ReferenceId,
    pub module: ModuleId,
    pub source_scope: ScopeId,
    pub source_context: ContextId,
    pub source_spelling: String,
    pub semantic_name: String,
    pub lexical_target: Resolution<SymbolId>,
    pub lookup: LookupSemantics,
    pub binding_state: ReferenceBindingState,
    pub phase: ReferencePhase,
    pub role: ReferenceRole,
    pub origin_domain: OriginDomain,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub annotation_semantics: Option<AnnotationSemantics>,
    pub span: TextRange,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "state", content = "value")]
pub enum Resolution<T> {
    Resolved(T),
    Ambiguous(Vec<T>),
    External,
    Unresolved(UnresolvedReason),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "kind", content = "detail")]
pub enum UnresolvedReason {
    UnsupportedSyntax,
    InvalidGlobalDeclaration,
    InvalidNonlocalDeclaration,
    MissingNonlocalBinding,
    ConflictingDeclaration,
    DeferredAnnotation,
    UnsupportedAnnotation,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "kind")]
pub enum LookupSemantics {
    Direct,
    GlobalThenBuiltin {
        global_symbol: SymbolId,
    },
    ClassLocalThenGlobalThenBuiltin {
        class_symbol: SymbolId,
        global_symbol: SymbolId,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "state", content = "value")]
pub enum ReferenceBindingState {
    NotApplicable,
    Analyzed(BindingState),
    NotAnalyzed(FlowFailureReason),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct BindingState {
    pub reachability: LocalReachability,
    pub bindings: BindingSetId,
    pub residual: ResidualLookup,
    pub uncertainty: FlowUncertaintySetId,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LocalReachability {
    MayExecute,
    Unreachable,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResidualLookup {
    None,
    UnboundLocal,
    RuntimeGlobalThenBuiltin,
    RuntimeFreeVariable,
    BuiltinOrNameError,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct FlowUncertaintySetFact {
    pub id: FlowUncertaintySetId,
    pub uncertainties: Vec<FlowUncertaintyKind>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlowUncertaintyKind {
    OpaqueCallMayMutateGlobal,
    OpaqueCallMayMutateClosure,
    DynamicNamespaceMutation,
    SuspensionPoint,
    ComplexExceptionFlow,
    FailedPartialMatch,
    UnsupportedFlow,
    UnsupportedAnnotation,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ContextFlowStatusFact {
    pub context: ContextId,
    pub status: ContextFlowStatus,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "status", content = "reason")]
pub enum ContextFlowStatus {
    Complete,
    Unsupported(FlowFailureReason),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "kind", content = "detail")]
pub enum FlowFailureReason {
    ResourceBudgetExceeded(FlowResourceBudget),
    UnsupportedAnnotation,
    UnsupportedFlow,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlowResourceBudget {
    BlockCount,
    WorklistIterations,
    StoredFlowFacts,
    BindingSetMemory,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "kind", content = "loop_id")]
pub enum CompletionKind {
    Normal,
    Return,
    Raise,
    Break(LoopId),
    Continue(LoopId),
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReferencePhase {
    DefinitionTime,
    BodyRuntime,
    TypeOnly,
    LazyAnnotation,
    ImportTime,
    ExportSurface,
    Root,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReferenceRole {
    Value,
    Call,
    Import,
    ModuleAttribute,
    Export,
    Decorator,
    DefaultValue,
    Annotation,
    BaseClass,
    ClassKeyword,
    Metaclass,
    ComprehensionIterable,
    ConfiguredRoot,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OriginDomain {
    Production,
    Test,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OriginEvidence {
    CullConfiguration,
    PytestTestPath,
    TestsDirectory,
    PytestFilenamePattern,
    DefaultProduction,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AnnotationEvaluation {
    Eager,
    Stringified,
    Deferred,
    NeverEvaluated,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct AnnotationSemantics {
    pub evaluation: AnnotationEvaluation,
    pub phase: ReferencePhase,
    pub scope: ScopeId,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DefinitionRole {
    Normal,
    OverloadDeclaration,
    OverloadImplementation,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DefinitionEffectKind {
    DecoratorApplication,
    DefaultExpressionEvaluation,
    EagerAnnotationEvaluation,
    ClassBaseEvaluation,
    ClassKeywordEvaluation,
    MetaclassEvaluation,
    ClassBodyExecution,
    LazyAnnotationIntrospectionRisk,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct DefinitionEffectSetFact {
    pub id: DefinitionEffectSetId,
    pub effects: Vec<DefinitionEffectKind>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", tag = "risk", content = "effects")]
pub enum RemovalRisk {
    NoKnownDefinitionEffects,
    Review(DefinitionEffectSetId),
    Unknown,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct OverloadGroupFact {
    pub id: OverloadGroupId,
    pub scope: ScopeId,
    pub name: String,
    pub declarations: Vec<DefId>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub implementation: Option<DefId>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InternalCandidateRule {
    UnreferencedFunction,
    UnreferencedClass,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InternalCandidateDisposition {
    Candidate,
    Suppressed,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InternalCandidateReason {
    NoSameModuleReferences,
    HasSameModuleReferences,
    NonReportableDefinition,
    OverloadDeclaration,
    UnresolvedOrUnsupportedReference,
    CrossModuleAnalysisDeferred,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct InternalCandidateFact {
    pub id: InternalCandidateId,
    pub definition: DefId,
    pub rule: InternalCandidateRule,
    pub disposition: InternalCandidateDisposition,
    pub reasons: Vec<InternalCandidateReason>,
    pub inbound_references: Vec<ReferenceId>,
    pub removal_risk: RemovalRisk,
}

#[derive(Debug, Default)]
pub struct SemanticGraphBuilder {
    graph: SemanticGraph,
    symbols_by_scope_name: BTreeMap<(ScopeId, String), SymbolId>,
    binding_sets_by_bindings: BTreeMap<Vec<BindingId>, BindingSetId>,
    definition_effect_sets_by_kinds: BTreeMap<Vec<DefinitionEffectKind>, DefinitionEffectSetId>,
    flow_uncertainty_sets_by_kinds: BTreeMap<Vec<FlowUncertaintyKind>, FlowUncertaintySetId>,
    last_binding_by_symbol: BTreeMap<SymbolId, BindingId>,
    next_binding_order_by_module: BTreeMap<ModuleId, u32>,
}

impl SemanticGraphBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn finish(self) -> SemanticGraph {
        self.graph
    }

    pub fn graph(&self) -> &SemanticGraph {
        &self.graph
    }

    pub fn add_scope_with_context(&mut self, input: ScopeContextInput) -> (ScopeId, ContextId) {
        let scope = ScopeId::new(self.graph.scopes.len() as u32);
        let context = ContextId::new(self.graph.contexts.len() as u32);

        self.graph.scopes.push(ScopeFact {
            id: scope,
            module: input.module,
            kind: input.scope_kind,
            parent: input.parent_scope,
            context,
            owner_definition: input.owner_definition,
            name: input.name,
            range: input.range,
        });
        self.graph.contexts.push(ContextFact {
            id: context,
            module: input.module,
            kind: input.context_kind,
            scope,
            parent: input.parent_context,
            owner_definition: input.owner_definition,
            range: input.range,
        });
        self.graph
            .context_flow_statuses
            .push(ContextFlowStatusFact {
                context,
                status: ContextFlowStatus::Complete,
            });

        (scope, context)
    }

    pub fn add_module(&mut self, module: SemanticModule) {
        self.graph.modules.push(module);
    }

    pub fn symbol(&mut self, module: ModuleId, scope: ScopeId, name: &str) -> SymbolId {
        let key = (scope, name.to_owned());
        if let Some(id) = self.symbols_by_scope_name.get(&key) {
            return *id;
        }

        let id = SymbolId::new(self.graph.symbols.len() as u32);
        self.graph.symbols.push(SymbolFact {
            id,
            module,
            scope,
            name: name.to_owned(),
        });
        self.symbols_by_scope_name.insert(key, id);
        id
    }

    pub fn add_binding(&mut self, input: BindingInput) -> BindingId {
        let id = BindingId::new(self.graph.bindings.len() as u32);
        let order = self
            .next_binding_order_by_module
            .entry(input.module)
            .and_modify(|next| *next += 1)
            .or_insert(1);
        let order = *order - 1;
        let replaces = self.last_binding_by_symbol.insert(input.symbol, id);

        self.graph.bindings.push(BindingFact {
            id,
            module: input.module,
            scope: input.scope,
            symbol: input.symbol,
            kind: input.kind,
            name: input.name,
            order,
            range: input.range,
            name_range: input.name_range,
            definition: None,
            replaces,
        });

        id
    }

    pub fn add_definition(&mut self, input: DefinitionInput) -> DefId {
        let id = DefId::new(self.graph.definitions.len() as u32);
        let no_effects = self.intern_definition_effect_set([]);
        self.graph.definitions.push(SemanticDefinition {
            id,
            module: input.module,
            binding: input.binding,
            scope: input.scope,
            context: input.context,
            kind: input.kind,
            name: input.name,
            qualified_name: input.qualified_name,
            range: input.range,
            name_range: input.name_range,
            reportable: input.reportable,
            is_async: input.is_async,
            role: DefinitionRole::Normal,
            overload_group: None,
            definition_effects: no_effects,
            removal_risk: RemovalRisk::NoKnownDefinitionEffects,
            origin_domain: input.origin_domain,
        });

        self.binding_mut(input.binding).definition = Some(id);
        self.scope_mut(input.scope).owner_definition = Some(id);
        self.context_mut(input.context).owner_definition = Some(id);

        id
    }

    pub fn add_reference(&mut self, input: ReferenceInput) -> ReferenceId {
        let id = ReferenceId::new(self.graph.references.len() as u32);
        self.graph.references.push(ReferenceFact {
            id,
            module: input.module,
            source_scope: input.source_scope,
            source_context: input.source_context,
            source_spelling: input.source_spelling,
            semantic_name: input.semantic_name,
            lexical_target: input.lexical_target,
            lookup: input.lookup,
            binding_state: input.binding_state,
            phase: input.phase,
            role: input.role,
            origin_domain: input.origin_domain,
            annotation_semantics: input.annotation_semantics,
            span: input.span,
        });
        id
    }

    pub fn intern_binding_set<I>(&mut self, bindings: I) -> BindingSetId
    where
        I: IntoIterator<Item = BindingId>,
    {
        let mut bindings = bindings.into_iter().collect::<Vec<_>>();
        bindings.sort();
        bindings.dedup();

        if let Some(id) = self.binding_sets_by_bindings.get(&bindings) {
            return *id;
        }

        let id = BindingSetId::new(self.graph.binding_sets.len() as u32);
        self.graph.binding_sets.push(BindingSetFact {
            id,
            bindings: bindings.clone(),
        });
        self.binding_sets_by_bindings.insert(bindings, id);
        id
    }

    pub fn intern_flow_uncertainty_set<I>(&mut self, uncertainties: I) -> FlowUncertaintySetId
    where
        I: IntoIterator<Item = FlowUncertaintyKind>,
    {
        let mut uncertainties = uncertainties.into_iter().collect::<Vec<_>>();
        uncertainties.sort();
        uncertainties.dedup();

        if let Some(id) = self.flow_uncertainty_sets_by_kinds.get(&uncertainties) {
            return *id;
        }

        let id = FlowUncertaintySetId::new(self.graph.flow_uncertainty_sets.len() as u32);
        self.graph
            .flow_uncertainty_sets
            .push(FlowUncertaintySetFact {
                id,
                uncertainties: uncertainties.clone(),
            });
        self.flow_uncertainty_sets_by_kinds
            .insert(uncertainties, id);
        id
    }

    pub fn intern_definition_effect_set<I>(&mut self, effects: I) -> DefinitionEffectSetId
    where
        I: IntoIterator<Item = DefinitionEffectKind>,
    {
        let mut effects = effects.into_iter().collect::<Vec<_>>();
        effects.sort();
        effects.dedup();

        if let Some(id) = self.definition_effect_sets_by_kinds.get(&effects) {
            return *id;
        }

        let id = DefinitionEffectSetId::new(self.graph.definition_effect_sets.len() as u32);
        self.graph
            .definition_effect_sets
            .push(DefinitionEffectSetFact {
                id,
                effects: effects.clone(),
            });
        self.definition_effect_sets_by_kinds.insert(effects, id);
        id
    }

    pub fn set_reference_binding_state(
        &mut self,
        reference: ReferenceId,
        binding_state: ReferenceBindingState,
    ) {
        self.reference_mut(reference).binding_state = binding_state;
    }

    pub fn set_context_flow_status(&mut self, context: ContextId, status: ContextFlowStatus) {
        if let Some(fact) = self
            .graph
            .context_flow_statuses
            .iter_mut()
            .find(|fact| fact.context == context)
        {
            fact.status = status;
        }
    }

    pub fn set_definition_effects(
        &mut self,
        definition: DefId,
        effects: DefinitionEffectSetId,
        removal_risk: RemovalRisk,
    ) {
        let definition = self.definition_mut(definition);
        definition.definition_effects = effects;
        definition.removal_risk = removal_risk;
    }

    pub fn set_definition_role(
        &mut self,
        definition: DefId,
        role: DefinitionRole,
        overload_group: Option<OverloadGroupId>,
    ) {
        let definition = self.definition_mut(definition);
        definition.role = role;
        definition.overload_group = overload_group;
        if role == DefinitionRole::OverloadDeclaration {
            definition.reportable = false;
        }
    }

    pub fn add_overload_group(
        &mut self,
        scope: ScopeId,
        name: String,
        declarations: Vec<DefId>,
        implementation: Option<DefId>,
    ) -> OverloadGroupId {
        let id = OverloadGroupId::new(self.graph.overload_groups.len() as u32);
        self.graph.overload_groups.push(OverloadGroupFact {
            id,
            scope,
            name,
            declarations,
            implementation,
        });
        id
    }

    pub fn add_internal_candidate(&mut self, input: InternalCandidateInput) -> InternalCandidateId {
        let id = InternalCandidateId::new(self.graph.internal_candidates.len() as u32);
        self.graph.internal_candidates.push(InternalCandidateFact {
            id,
            definition: input.definition,
            rule: input.rule,
            disposition: input.disposition,
            reasons: input.reasons,
            inbound_references: input.inbound_references,
            removal_risk: input.removal_risk,
        });
        id
    }

    fn binding_mut(&mut self, id: BindingId) -> &mut BindingFact {
        &mut self.graph.bindings[id.as_u32() as usize]
    }

    fn scope_mut(&mut self, id: ScopeId) -> &mut ScopeFact {
        &mut self.graph.scopes[id.as_u32() as usize]
    }

    fn context_mut(&mut self, id: ContextId) -> &mut ContextFact {
        &mut self.graph.contexts[id.as_u32() as usize]
    }

    fn definition_mut(&mut self, id: DefId) -> &mut SemanticDefinition {
        &mut self.graph.definitions[id.as_u32() as usize]
    }

    fn reference_mut(&mut self, id: ReferenceId) -> &mut ReferenceFact {
        &mut self.graph.references[id.as_u32() as usize]
    }
}

#[derive(Clone, Debug)]
pub struct ScopeContextInput {
    pub module: ModuleId,
    pub scope_kind: ScopeKind,
    pub context_kind: ContextKind,
    pub parent_scope: Option<ScopeId>,
    pub parent_context: Option<ContextId>,
    pub owner_definition: Option<DefId>,
    pub name: String,
    pub range: TextRange,
}

#[derive(Clone, Debug)]
pub struct BindingInput {
    pub module: ModuleId,
    pub scope: ScopeId,
    pub symbol: SymbolId,
    pub kind: BindingKind,
    pub name: String,
    pub range: TextRange,
    pub name_range: TextRange,
}

#[derive(Clone, Debug)]
pub struct DefinitionInput {
    pub module: ModuleId,
    pub binding: BindingId,
    pub scope: ScopeId,
    pub context: ContextId,
    pub kind: DefinitionKind,
    pub name: String,
    pub qualified_name: String,
    pub range: TextRange,
    pub name_range: TextRange,
    pub reportable: bool,
    pub is_async: bool,
    pub origin_domain: OriginDomain,
}

#[derive(Clone, Debug)]
pub struct ReferenceInput {
    pub module: ModuleId,
    pub source_scope: ScopeId,
    pub source_context: ContextId,
    pub source_spelling: String,
    pub semantic_name: String,
    pub lexical_target: Resolution<SymbolId>,
    pub lookup: LookupSemantics,
    pub binding_state: ReferenceBindingState,
    pub phase: ReferencePhase,
    pub role: ReferenceRole,
    pub origin_domain: OriginDomain,
    pub annotation_semantics: Option<AnnotationSemantics>,
    pub span: TextRange,
}

#[derive(Clone, Debug)]
pub struct InternalCandidateInput {
    pub definition: DefId,
    pub rule: InternalCandidateRule,
    pub disposition: InternalCandidateDisposition,
    pub reasons: Vec<InternalCandidateReason>,
    pub inbound_references: Vec<ReferenceId>,
    pub removal_risk: RemovalRisk,
}
