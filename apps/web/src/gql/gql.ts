/* eslint-disable */
import * as types from './graphql';
import type { TypedDocumentNode as DocumentNode } from '@graphql-typed-document-node/core';

/**
 * Map of all GraphQL operations in the project.
 *
 * This map has several performance disadvantages:
 * 1. It is not tree-shakeable, so it will include all operations in the project.
 * 2. It is not minifiable, so the string of a GraphQL query will be multiple times inside the bundle.
 * 3. It does not support dead code elimination, so it will add unused operations.
 *
 * Therefore it is highly recommended to use the babel or swc plugin for production.
 * Learn more about it here: https://the-guild.dev/graphql/codegen/plugins/presets/preset-client#reducing-bundle-size
 */
type Documents = {
    "\n  fragment ListInvoiceFields on Invoice {\n    id\n    status\n    invoiceNumber\n    originalFilename\n    poNumber\n    createdAt\n    vendor { name }\n    total { amountMinor currency }\n    invalidFields\n    match { reasons { code detail line } }\n    pendingAction { id status actionType details }\n  }\n": typeof types.ListInvoiceFieldsFragmentDoc,
    "\n  query ExceptionsQueue($first: Int!, $after: String) {\n    exceptionsQueue(first: $first, after: $after) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n": typeof types.ExceptionsQueueDocument,
    "\n  query Invoices($first: Int!, $after: String, $status: String) {\n    invoices(first: $first, after: $after, status: $status) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n": typeof types.InvoicesDocument,
    "\n  fragment PendingActionFields on PendingAction {\n    id\n    invoiceId\n    actionType\n    status\n    details\n    version\n    decisionNote\n    createdAt\n    decidedAt\n  }\n": typeof types.PendingActionFieldsFragmentDoc,
    "\n  query Case($id: UUID!) {\n    invoice(id: $id) {\n      id\n      status\n      originalFilename\n      pageCount\n      invoiceNumber\n      poNumber\n      invoiceDate\n      dueDate\n      currency\n      subtotal { amountMinor currency }\n      tax { amountMinor currency }\n      total { amountMinor currency }\n      invalidFields\n      fieldConfidence\n      errorCode\n      errorDetail\n      model\n      promptVersion\n      llmMs\n      repairAttempted\n      createdAt\n      vendor { id name taxId }\n      lines { pageNo lineNo description quantity unitPrice amount { amountMinor currency } invalidReason }\n      pages { pageNo status source errorCode llmMs }\n      match { status purchaseOrderId matchedAt reasons { code detail line } }\n      purchaseOrder { poNumber lines { lineNo description quantity unitPrice } }\n      goodsReceipts { receivedOn lines { poLineNo quantity } }\n      pendingAction { ...PendingActionFields }\n      agentRuns {\n        id status stopReason model promptVersion toolTurns guardFires llmMs startedAt finishedAt\n        steps { stepNo kind content toolName arguments result error llmMs }\n      }\n    }\n  }\n": typeof types.CaseDocument,
    "\n  query InvoiceStatus($id: UUID!) {\n    invoice(id: $id) { id status invoiceNumber total { amountMinor currency } }\n  }\n": typeof types.InvoiceStatusDocument,
    "\n  mutation Approve($id: UUID!, $expectedVersion: Int!, $note: String) {\n    approvePendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n": typeof types.ApproveDocument,
    "\n  mutation Reject($id: UUID!, $expectedVersion: Int!, $note: String) {\n    rejectPendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n": typeof types.RejectDocument,
};
const documents: Documents = {
    "\n  fragment ListInvoiceFields on Invoice {\n    id\n    status\n    invoiceNumber\n    originalFilename\n    poNumber\n    createdAt\n    vendor { name }\n    total { amountMinor currency }\n    invalidFields\n    match { reasons { code detail line } }\n    pendingAction { id status actionType details }\n  }\n": types.ListInvoiceFieldsFragmentDoc,
    "\n  query ExceptionsQueue($first: Int!, $after: String) {\n    exceptionsQueue(first: $first, after: $after) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n": types.ExceptionsQueueDocument,
    "\n  query Invoices($first: Int!, $after: String, $status: String) {\n    invoices(first: $first, after: $after, status: $status) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n": types.InvoicesDocument,
    "\n  fragment PendingActionFields on PendingAction {\n    id\n    invoiceId\n    actionType\n    status\n    details\n    version\n    decisionNote\n    createdAt\n    decidedAt\n  }\n": types.PendingActionFieldsFragmentDoc,
    "\n  query Case($id: UUID!) {\n    invoice(id: $id) {\n      id\n      status\n      originalFilename\n      pageCount\n      invoiceNumber\n      poNumber\n      invoiceDate\n      dueDate\n      currency\n      subtotal { amountMinor currency }\n      tax { amountMinor currency }\n      total { amountMinor currency }\n      invalidFields\n      fieldConfidence\n      errorCode\n      errorDetail\n      model\n      promptVersion\n      llmMs\n      repairAttempted\n      createdAt\n      vendor { id name taxId }\n      lines { pageNo lineNo description quantity unitPrice amount { amountMinor currency } invalidReason }\n      pages { pageNo status source errorCode llmMs }\n      match { status purchaseOrderId matchedAt reasons { code detail line } }\n      purchaseOrder { poNumber lines { lineNo description quantity unitPrice } }\n      goodsReceipts { receivedOn lines { poLineNo quantity } }\n      pendingAction { ...PendingActionFields }\n      agentRuns {\n        id status stopReason model promptVersion toolTurns guardFires llmMs startedAt finishedAt\n        steps { stepNo kind content toolName arguments result error llmMs }\n      }\n    }\n  }\n": types.CaseDocument,
    "\n  query InvoiceStatus($id: UUID!) {\n    invoice(id: $id) { id status invoiceNumber total { amountMinor currency } }\n  }\n": types.InvoiceStatusDocument,
    "\n  mutation Approve($id: UUID!, $expectedVersion: Int!, $note: String) {\n    approvePendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n": types.ApproveDocument,
    "\n  mutation Reject($id: UUID!, $expectedVersion: Int!, $note: String) {\n    rejectPendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n": types.RejectDocument,
};

/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 *
 *
 * @example
 * ```ts
 * const query = graphql(`query GetUser($id: ID!) { user(id: $id) { name } }`);
 * ```
 *
 * The query argument is unknown!
 * Please regenerate the types.
 */
export function graphql(source: string): unknown;

/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  fragment ListInvoiceFields on Invoice {\n    id\n    status\n    invoiceNumber\n    originalFilename\n    poNumber\n    createdAt\n    vendor { name }\n    total { amountMinor currency }\n    invalidFields\n    match { reasons { code detail line } }\n    pendingAction { id status actionType details }\n  }\n"): (typeof documents)["\n  fragment ListInvoiceFields on Invoice {\n    id\n    status\n    invoiceNumber\n    originalFilename\n    poNumber\n    createdAt\n    vendor { name }\n    total { amountMinor currency }\n    invalidFields\n    match { reasons { code detail line } }\n    pendingAction { id status actionType details }\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  query ExceptionsQueue($first: Int!, $after: String) {\n    exceptionsQueue(first: $first, after: $after) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n"): (typeof documents)["\n  query ExceptionsQueue($first: Int!, $after: String) {\n    exceptionsQueue(first: $first, after: $after) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  query Invoices($first: Int!, $after: String, $status: String) {\n    invoices(first: $first, after: $after, status: $status) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n"): (typeof documents)["\n  query Invoices($first: Int!, $after: String, $status: String) {\n    invoices(first: $first, after: $after, status: $status) {\n      edges { cursor node { ...ListInvoiceFields } }\n      pageInfo { hasNextPage endCursor }\n    }\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  fragment PendingActionFields on PendingAction {\n    id\n    invoiceId\n    actionType\n    status\n    details\n    version\n    decisionNote\n    createdAt\n    decidedAt\n  }\n"): (typeof documents)["\n  fragment PendingActionFields on PendingAction {\n    id\n    invoiceId\n    actionType\n    status\n    details\n    version\n    decisionNote\n    createdAt\n    decidedAt\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  query Case($id: UUID!) {\n    invoice(id: $id) {\n      id\n      status\n      originalFilename\n      pageCount\n      invoiceNumber\n      poNumber\n      invoiceDate\n      dueDate\n      currency\n      subtotal { amountMinor currency }\n      tax { amountMinor currency }\n      total { amountMinor currency }\n      invalidFields\n      fieldConfidence\n      errorCode\n      errorDetail\n      model\n      promptVersion\n      llmMs\n      repairAttempted\n      createdAt\n      vendor { id name taxId }\n      lines { pageNo lineNo description quantity unitPrice amount { amountMinor currency } invalidReason }\n      pages { pageNo status source errorCode llmMs }\n      match { status purchaseOrderId matchedAt reasons { code detail line } }\n      purchaseOrder { poNumber lines { lineNo description quantity unitPrice } }\n      goodsReceipts { receivedOn lines { poLineNo quantity } }\n      pendingAction { ...PendingActionFields }\n      agentRuns {\n        id status stopReason model promptVersion toolTurns guardFires llmMs startedAt finishedAt\n        steps { stepNo kind content toolName arguments result error llmMs }\n      }\n    }\n  }\n"): (typeof documents)["\n  query Case($id: UUID!) {\n    invoice(id: $id) {\n      id\n      status\n      originalFilename\n      pageCount\n      invoiceNumber\n      poNumber\n      invoiceDate\n      dueDate\n      currency\n      subtotal { amountMinor currency }\n      tax { amountMinor currency }\n      total { amountMinor currency }\n      invalidFields\n      fieldConfidence\n      errorCode\n      errorDetail\n      model\n      promptVersion\n      llmMs\n      repairAttempted\n      createdAt\n      vendor { id name taxId }\n      lines { pageNo lineNo description quantity unitPrice amount { amountMinor currency } invalidReason }\n      pages { pageNo status source errorCode llmMs }\n      match { status purchaseOrderId matchedAt reasons { code detail line } }\n      purchaseOrder { poNumber lines { lineNo description quantity unitPrice } }\n      goodsReceipts { receivedOn lines { poLineNo quantity } }\n      pendingAction { ...PendingActionFields }\n      agentRuns {\n        id status stopReason model promptVersion toolTurns guardFires llmMs startedAt finishedAt\n        steps { stepNo kind content toolName arguments result error llmMs }\n      }\n    }\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  query InvoiceStatus($id: UUID!) {\n    invoice(id: $id) { id status invoiceNumber total { amountMinor currency } }\n  }\n"): (typeof documents)["\n  query InvoiceStatus($id: UUID!) {\n    invoice(id: $id) { id status invoiceNumber total { amountMinor currency } }\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  mutation Approve($id: UUID!, $expectedVersion: Int!, $note: String) {\n    approvePendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n"): (typeof documents)["\n  mutation Approve($id: UUID!, $expectedVersion: Int!, $note: String) {\n    approvePendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n"];
/**
 * The graphql function is used to parse GraphQL queries into a document that can be used by GraphQL clients.
 */
export function graphql(source: "\n  mutation Reject($id: UUID!, $expectedVersion: Int!, $note: String) {\n    rejectPendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n"): (typeof documents)["\n  mutation Reject($id: UUID!, $expectedVersion: Int!, $note: String) {\n    rejectPendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {\n      __typename\n      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }\n      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }\n      ... on NotFound { id }\n    }\n  }\n"];

export function graphql(source: string) {
  return (documents as any)[source] ?? {};
}

export type DocumentType<TDocumentNode extends DocumentNode<any, any>> = TDocumentNode extends DocumentNode<  infer TType,  any>  ? TType  : never;