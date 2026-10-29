// Package vaquill is the Go client for the Vaquill US Data API: statutes, regulations, court
// rules, constitutions and session laws, plus law-change alerts.
//
// Create a client, then call a method on one of its services. Every method takes a
// context.Context first, returns a typed value and a typed error, and never panics.
//
//	client, err := vaquill.NewClient() // reads VAQUILL_API_KEY
//	if err != nil {
//		log.Fatal(err)
//	}
//	res, err := client.Statutes.Resolve(ctx, "42 U.S.C. 1983", nil)
//
// # Charged calls
//
// Most operations spend credits (Operations reports which). A charged call gets an
// Idempotency-Key automatically, is retried safely, and counts toward WithMaxCredits. Credits
// consumed are read from the response, so the guard is exact.
//
// # Errors
//
// API failures are typed (*RateLimitError, *NotFoundError, ...) and all unwrap to *APIError.
// Use errors.As for the type and errors.Is with the Err* sentinels. Every SDK error implements
// the Error interface.
//
// # Models and operations
//
// models_gen.go, operations_gen.go and operations_meta_gen.go are generated from
// openapi/vaquill-us.json by internal/gen (go generate). A test fails when the committed files
// differ from a fresh generation.
package vaquill

//go:generate go run ./internal/gen -spec ../openapi/vaquill-us.json -out .
