package vaquill

// OperationInfo describes one operation of the frozen contract.
type OperationInfo struct {
	// ID is the operationId in openapi/vaquill-us.json.
	ID     string
	Method string
	Path   string
	// Service and GoMethod locate the SDK method, for example Statutes.Search.
	Service  string
	GoMethod string
	// Charged operations consume credits: they send an Idempotency-Key and count toward WithMaxCredits.
	Charged bool
}

// StatutesService is client.Statutes: US statutes, regulations, rules and constitutions.
type StatutesService struct{ c *Client }

// SessionLawsService is client.SessionLaws: acts as enacted.
type SessionLawsService struct{ c *Client }

// WatchesService is client.Watches: law-change alerts. Free except ChangeDiff.
type WatchesService struct{ c *Client }

// BoardsService is client.Boards: the sources a watch can follow (free).
type BoardsService struct{ c *Client }

// CreditsService is client.Credits: the credit balance (free).
type CreditsService struct{ c *Client }

// PricingService is client.Pricing: the credit price of every endpoint (free).
type PricingService struct{ c *Client }
