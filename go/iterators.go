package vaquill

import "context"

func setDefault(m map[string]any, k string, v any) {
	if _, ok := m[k]; !ok {
		m[k] = v
	}
}

// IterSearch pages through POST /us/statutes/search. Every page is a charged call.
func (s *StatutesService) IterSearch(ctx context.Context, req *StatuteSearchRequest, opts ...PageOption) (*Paginator[StatuteResult], error) {
	if req == nil {
		return nil, errNilRequest("StatuteSearchRequest")
	}
	params, err := toMap(req)
	if err != nil {
		return nil, err
	}
	setDefault(params, "offset", int64(0))
	cfg := newPageConfig(opts)
	return newPaginator[StatuteResult](s.c, cfg, "results", nextOffsetOrHasMore{}, params,
		s.c.pageFetch(ctx, "POST", "/api/v1/us/statutes/search", true, false, cfg)), nil
}

// IterDivisions pages through GET /us/statutes/divisions by cursor. Every page is a charged call.
func (s *StatutesService) IterDivisions(ctx context.Context, corpusType string, params *ListStatuteDivisionsParams, opts ...PageOption) (*Paginator[UsDivisionNode], error) {
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	m["corpusType"] = corpusType
	cfg := newPageConfig(opts)
	return newPaginator[UsDivisionNode](s.c, cfg, "divisions", cursorStyle{}, m,
		s.c.pageFetch(ctx, "GET", "/api/v1/us/statutes/divisions", true, false, cfg)), nil
}

// IterSectionChanges pages through a section's change history (limit 50 and newest first unless
// params say otherwise). Every page is a charged call.
func (s *StatutesService) IterSectionChanges(ctx context.Context, actID string, params *GetSectionChangesParams, opts ...PageOption) (*Paginator[StatuteChangeEvent], error) {
	path, err := pathf("/api/v1/us/statutes/section/{act_id}/changes", "act_id", actID)
	if err != nil {
		return nil, err
	}
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	setDefault(m, "limit", int64(50))
	setDefault(m, "order", "desc")
	param := "beforeId"
	if m["order"] == "asc" {
		param = "sinceId"
	}
	cfg := newPageConfig(opts)
	return newPaginator[StatuteChangeEvent](s.c, cfg, "changes", hasMoreID{param}, m, s.c.pageFetch(ctx, "GET", path, true, false, cfg)), nil
}

// IterSearch pages through POST /us/session-laws/search (limit 10 unless set). Every page is a charged call.
func (s *SessionLawsService) IterSearch(ctx context.Context, req *SessionLawSearchRequest, opts ...PageOption) (*Paginator[SessionLawSearchResult], error) {
	if req == nil {
		return nil, errNilRequest("SessionLawSearchRequest")
	}
	params, err := toMap(req)
	if err != nil {
		return nil, err
	}
	setDefault(params, "limit", int64(10))
	setDefault(params, "offset", int64(0))
	cfg := newPageConfig(opts)
	return newPaginator[SessionLawSearchResult](s.c, cfg, "results", hasMoreOffset{}, params,
		s.c.pageFetch(ctx, "POST", "/api/v1/us/session-laws/search", true, false, cfg)), nil
}

// IterList pages through GET /us/session-laws/list by cursor. Every page is a charged call.
func (s *SessionLawsService) IterList(ctx context.Context, jurisdiction string, params *ListSessionLawsParams, opts ...PageOption) (*Paginator[SessionLawSummary], error) {
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	m["jurisdiction"] = jurisdiction
	cfg := newPageConfig(opts)
	return newPaginator[SessionLawSummary](s.c, cfg, "results", cursorStyle{}, m,
		s.c.pageFetch(ctx, "GET", "/api/v1/us/session-laws/list", true, false, cfg)), nil
}

// IterBody reads a session law's text page by page. Each element is one page; later pages are
// addressed by the cursor alone. Every page is a charged call.
func (s *SessionLawsService) IterBody(ctx context.Context, sessionLawID string, params *GetSessionLawBodyParams, opts ...PageOption) (*Paginator[SessionLawBodyResponse], error) {
	path, err := pathf("/api/v1/us/session-laws/{session_law_id}/body", "session_law_id", sessionLawID)
	if err != nil {
		return nil, err
	}
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	cfg := newPageConfig(opts)
	return newPaginator[SessionLawBodyResponse](s.c, cfg, "", hasMoreCursor{}, m, s.c.pageFetch(ctx, "GET", path, true, false, cfg)), nil
}

// IterChanges pages through the session-law change feed forward from sinceId (default 0, limit 50). Every page is a charged call.
func (s *SessionLawsService) IterChanges(ctx context.Context, params *GetSessionLawChangesParams, opts ...PageOption) (*Paginator[SessionLawChange], error) {
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	setDefault(m, "sinceId", int64(0))
	setDefault(m, "limit", int64(50))
	cfg := newPageConfig(opts)
	return newPaginator[SessionLawChange](s.c, cfg, "changes", hasMoreID{"sinceId"}, m,
		s.c.pageFetch(ctx, "GET", "/api/v1/us/session-laws/changes", true, false, cfg)), nil
}

// IterList pages through every board (limit 500). Free.
func (b *BoardsService) IterList(ctx context.Context, params *ListBoardsParams, opts ...PageOption) (*Paginator[BoardResponse], error) {
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	setDefault(m, "limit", int64(500))
	setDefault(m, "offset", int64(0))
	cfg := newPageConfig(opts)
	return newPaginator[BoardResponse](b.c, cfg, "boards", hasMoreOffset{}, m,
		b.c.pageFetch(ctx, "GET", "/api/v1/boards", false, true, cfg)), nil
}

// IterList pages through all your watches (limit 100). Free.
func (w *WatchesService) IterList(ctx context.Context, params *ListWatchesParams, opts ...PageOption) (*Paginator[WatchResponse], error) {
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	setDefault(m, "limit", int64(100))
	setDefault(m, "offset", int64(0))
	cfg := newPageConfig(opts)
	return newPaginator[WatchResponse](w.c, cfg, "watches", hasMoreOffset{}, m,
		w.c.pageFetch(ctx, "GET", "/api/v1/watches", false, true, cfg)), nil
}

// IterChanges pages through a watch's changes (limit 50, newest first unless order is "asc"). Free.
func (w *WatchesService) IterChanges(ctx context.Context, watchID string, params *ListWatchChangesParams, opts ...PageOption) (*Paginator[ChangeResponse], error) {
	path, err := pathf("/api/v1/watches/{watch_id}/changes", "watch_id", watchID)
	if err != nil {
		return nil, err
	}
	m, err := toMap(params)
	if err != nil {
		return nil, err
	}
	setDefault(m, "limit", int64(50))
	setDefault(m, "order", "desc")
	param := "beforeId"
	if m["order"] == "asc" {
		param = "sinceId"
	}
	cfg := newPageConfig(opts)
	return newPaginator[ChangeResponse](w.c, cfg, "changes", hasMoreID{param}, m, w.c.pageFetch(ctx, "GET", path, false, true, cfg)), nil
}
