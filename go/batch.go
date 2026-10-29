package vaquill

import (
	"context"
	"strconv"
)

// Per-call item limits (maxItems in the spec).
const (
	// ResolveBatchMax is the citations per POST /us/statutes/resolve call.
	ResolveBatchMax = 500
	// SectionsBatchMax is the ids per POST /us/statutes/sections call.
	SectionsBatchMax = 50
	// SessionLawBatchMax is the ids per POST /us/session-laws/batch call.
	SessionLawBatchMax = 200
)

// chunked splits items into consecutive slices of at most size.
func chunked(items []string, size int) [][]string {
	var out [][]string
	for start := 0; start < len(items); start += size {
		end := start + size
		if end > len(items) {
			end = len(items)
		}
		out = append(out, items[start:end])
	}
	return out
}

// unique drops exact repeats, keeping the first occurrence and the order.
func unique(items []string) []string {
	seen := make(map[string]struct{}, len(items))
	out := make([]string, 0, len(items))
	for _, s := range items {
		if _, ok := seen[s]; !ok {
			seen[s] = struct{}{}
			out = append(out, s)
		}
	}
	return out
}

// chunkOptions suffixes a caller's idempotency key for chunks after the first. Every chunk has a
// different body, so reusing one key would be rejected as a key reuse.
func chunkOptions(opts []CallOption, index int) []CallOption {
	if index == 0 {
		return opts
	}
	cfg := newCallConfig(opts)
	if cfg.idempotencyKey == nil {
		return opts
	}
	suffix := "-" + strconv.Itoa(index)
	key := *cfg.idempotencyKey
	if len(key) > 255-len(suffix) {
		key = key[:255-len(suffix)]
	}
	out := append([]CallOption(nil), opts...)
	return append(out, WithIdempotencyKey(key+suffix))
}

// ResolveBatchAll resolves any number of citations, 500 per call, after dropping exact repeats.
// Every chunk is a separate charged call. Results follow the order of the deduplicated citations.
func (s *StatutesService) ResolveBatchAll(ctx context.Context, req *StatuteResolveBatchRequest, opts ...CallOption) ([]StatuteResolveBatchItem, error) {
	if req == nil {
		return nil, errNilRequest("StatuteResolveBatchRequest")
	}
	var results []StatuteResolveBatchItem
	for i, chunk := range chunked(unique(req.Citations), ResolveBatchMax) {
		r := *req
		r.Citations = chunk
		resp, err := s.ResolveBatch(ctx, &r, chunkOptions(opts, i)...)
		if err != nil {
			return results, err
		}
		results = append(results, resp.Results...)
	}
	return results, nil
}

// GetSectionsAll fetches any number of sections, 50 ids per call, after dropping exact repeats.
// Every chunk is a separate charged call.
func (s *StatutesService) GetSectionsAll(ctx context.Context, req *StatuteSectionsRequest, opts ...CallOption) ([]StatuteResult, error) {
	if req == nil {
		return nil, errNilRequest("StatuteSectionsRequest")
	}
	var sections []StatuteResult
	for i, chunk := range chunked(unique(req.ActIds), SectionsBatchMax) {
		r := *req
		r.ActIds = chunk
		resp, err := s.GetSectionsBatch(ctx, &r, chunkOptions(opts, i)...)
		if err != nil {
			return sections, err
		}
		sections = append(sections, resp.Sections...)
	}
	return sections, nil
}

// GetBatchAll fetches any number of session laws, 200 ids per call, after dropping exact repeats.
// Every chunk is a separate charged call.
func (s *SessionLawsService) GetBatchAll(ctx context.Context, req *SessionLawBatchRequest, opts ...CallOption) ([]SessionLawBatchLaw, error) {
	if req == nil {
		return nil, errNilRequest("SessionLawBatchRequest")
	}
	var laws []SessionLawBatchLaw
	for i, chunk := range chunked(unique(req.Ids), SessionLawBatchMax) {
		r := *req
		r.Ids = chunk
		resp, err := s.GetBatch(ctx, &r, chunkOptions(opts, i)...)
		if err != nil {
			return laws, err
		}
		laws = append(laws, resp.Laws...)
	}
	return laws, nil
}
