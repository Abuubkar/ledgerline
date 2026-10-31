// Every GraphQL operation the UI sends. `pnpm codegen` turns these into typed documents in src/gql.
import { graphql } from "@/gql";

export const ListInvoiceFields = graphql(`
  fragment ListInvoiceFields on Invoice {
    id
    status
    invoiceNumber
    originalFilename
    poNumber
    createdAt
    vendor { name }
    total { amountMinor currency }
    invalidFields
    match { reasons { code detail line } }
    pendingAction { id status actionType details }
  }
`);

export const ExceptionsQueueQuery = graphql(`
  query ExceptionsQueue($first: Int!, $after: String) {
    exceptionsQueue(first: $first, after: $after) {
      edges { cursor node { ...ListInvoiceFields } }
      pageInfo { hasNextPage endCursor }
    }
  }
`);

export const InvoicesQuery = graphql(`
  query Invoices($first: Int!, $after: String, $status: String) {
    invoices(first: $first, after: $after, status: $status) {
      edges { cursor node { ...ListInvoiceFields } }
      pageInfo { hasNextPage endCursor }
    }
  }
`);

export const PendingActionFields = graphql(`
  fragment PendingActionFields on PendingAction {
    id
    invoiceId
    actionType
    status
    details
    version
    decisionNote
    createdAt
    decidedAt
  }
`);

export const CaseQuery = graphql(`
  query Case($id: UUID!) {
    invoice(id: $id) {
      id
      status
      originalFilename
      pageCount
      invoiceNumber
      poNumber
      invoiceDate
      dueDate
      currency
      subtotal { amountMinor currency }
      tax { amountMinor currency }
      total { amountMinor currency }
      invalidFields
      fieldConfidence
      errorCode
      errorDetail
      model
      promptVersion
      llmMs
      repairAttempted
      createdAt
      vendor { id name taxId }
      lines { pageNo lineNo description quantity unitPrice amount { amountMinor currency } invalidReason }
      pages { pageNo status source errorCode llmMs }
      match { status purchaseOrderId matchedAt reasons { code detail line } }
      purchaseOrder { poNumber lines { lineNo description quantity unitPrice } }
      goodsReceipts { receivedOn lines { poLineNo quantity } }
      pendingAction { ...PendingActionFields }
      agentRuns {
        id status stopReason model promptVersion toolTurns guardFires llmMs startedAt finishedAt
        steps { stepNo kind content toolName arguments result error llmMs }
      }
    }
  }
`);

export const StatusQuery = graphql(`
  query InvoiceStatus($id: UUID!) {
    invoice(id: $id) { id status invoiceNumber total { amountMinor currency } }
  }
`);

export const ApproveMutation = graphql(`
  mutation Approve($id: UUID!, $expectedVersion: Int!, $note: String) {
    approvePendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {
      __typename
      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }
      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }
      ... on NotFound { id }
    }
  }
`);

export const RejectMutation = graphql(`
  mutation Reject($id: UUID!, $expectedVersion: Int!, $note: String) {
    rejectPendingAction(id: $id, expectedVersion: $expectedVersion, note: $note) {
      __typename
      ... on DecisionSuccess { pendingAction { ...PendingActionFields } }
      ... on VersionConflict { currentVersion pendingAction { ...PendingActionFields } }
      ... on NotFound { id }
    }
  }
`);
