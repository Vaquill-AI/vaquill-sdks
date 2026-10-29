// Command gen generates models_gen.go, operations_gen.go and operations_meta_gen.go
// of the vaquill package from the frozen OpenAPI document.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"go/format"
	"sort"
	"strings"
	"unicode"
)

type obj = map[string]any

// opNames maps an operationId to its service and Go method (mirrors the Python SDK naming).
var opNames = map[string][2]string{
	"search_statutes":                 {"Statutes", "Search"},
	"resolve_statute_citation":        {"Statutes", "Resolve"},
	"resolve_statute_citations_batch": {"Statutes", "ResolveBatch"},
	"get_section":                     {"Statutes", "GetSection"},
	"get_section_body":                {"Statutes", "GetSectionBody"},
	"get_section_neighbors":           {"Statutes", "Neighbors"},
	"get_sections_batch":              {"Statutes", "GetSectionsBatch"},
	"count_statute_sections":          {"Statutes", "Count"},
	"list_statutes_coverage":          {"Statutes", "Coverage"},
	"list_statute_divisions":          {"Statutes", "Divisions"},
	"get_section_changes":             {"Statutes", "SectionChanges"},
	"get_section_enactments":          {"Statutes", "Enactments"},
	"get_section_rulemaking":          {"Statutes", "SectionRulemaking"},
	"get_part_rulemaking":             {"Statutes", "PartRulemaking"},
	"get_section_cited_by":            {"Statutes", "CitedBy"},
	"get_section_definitions":         {"Statutes", "Definitions"},
	"get_section_cross_state":         {"Statutes", "CrossState"},
	"extract_statute_citations":       {"Statutes", "ExtractCitations"},
	"search_session_laws":             {"SessionLaws", "Search"},
	"list_session_laws":               {"SessionLaws", "List"},
	"get_session_law":                 {"SessionLaws", "Get"},
	"get_session_law_body":            {"SessionLaws", "GetBody"},
	"get_session_law_versions":        {"SessionLaws", "Versions"},
	"get_session_laws_batch":          {"SessionLaws", "GetBatch"},
	"get_session_law_changes":         {"SessionLaws", "Changes"},
	"list_watches":                    {"Watches", "List"},
	"create_watch":                    {"Watches", "Create"},
	"update_watch":                    {"Watches", "Update"},
	"delete_watch":                    {"Watches", "Delete"},
	"test_watch":                      {"Watches", "Test"},
	"list_watch_changes":              {"Watches", "Changes"},
	"get_watch_change_diff":           {"Watches", "ChangeDiff"},
	"list_watch_deliveries":           {"Watches", "Deliveries"},
	"list_boards":                     {"Boards", "List"},
	"get_credit_balance":              {"Credits", "Balance"},
	"get_pricing":                     {"Pricing", "Get"},
}

var initialisms = map[string]string{
	"id": "ID", "url": "URL", "uri": "URI", "api": "API", "http": "HTTP", "https": "HTTPS",
	"json": "JSON", "html": "HTML", "pdf": "PDF", "ip": "IP", "uuid": "UUID", "cfr": "CFR",
	"usc": "USC", "sha256": "SHA256", "ocr": "OCR", "sql": "SQL",
}

type generator struct {
	schemas    obj
	hoisted    obj // inline object schemas promoted to named structs
	hoistOrder []string
	reqMode    map[string]bool
	warnings   []string
	structs    map[string]bool
	scalars    map[string]bool
}

// Generate renders the three generated files from the OpenAPI document.
func Generate(spec []byte) (map[string][]byte, []string, error) {
	var doc obj
	if err := json.Unmarshal(spec, &doc); err != nil {
		return nil, nil, err
	}
	comps, _ := doc["components"].(obj)
	schemas, _ := comps["schemas"].(obj)
	g := &generator{
		schemas: schemas, hoisted: obj{}, reqMode: map[string]bool{},
		structs: map[string]bool{}, scalars: map[string]bool{"string": true, "bool": true, "int": true, "float64": true, "time.Time": true},
	}
	for name, raw := range schemas {
		s := raw.(obj)
		if isStruct(s) {
			g.structs[name] = true
		} else if _, ok := s["enum"]; ok {
			g.scalars[name] = true
		}
	}
	paths, _ := doc["paths"].(obj)
	ops := g.collectOps(paths)
	g.markRequestSchemas(ops)

	// Operations first: resolving parameter schemas can hoist inline structs that models() emits.
	operations, err := g.operations(ops)
	if err != nil {
		return nil, nil, err
	}
	models, err := g.models()
	if err != nil {
		return nil, nil, err
	}
	meta, err := g.meta(ops)
	if err != nil {
		return nil, nil, err
	}
	return map[string][]byte{
		"models_gen.go":          models,
		"operations_gen.go":      operations,
		"operations_meta_gen.go": meta,
	}, g.warnings, nil
}

func isStruct(s obj) bool {
	_, ok := s["properties"].(obj)
	return ok
}

// ---------------------------------------------------------------- naming

func words(s string) []string {
	var out []string
	var cur []rune
	flush := func() {
		if len(cur) > 0 {
			out = append(out, string(cur))
			cur = nil
		}
	}
	rs := []rune(s)
	for i, r := range rs {
		switch {
		case !unicode.IsLetter(r) && !unicode.IsDigit(r):
			flush()
		case unicode.IsUpper(r):
			prevLower := i > 0 && (unicode.IsLower(rs[i-1]) || unicode.IsDigit(rs[i-1]))
			nextLower := i+1 < len(rs) && unicode.IsLower(rs[i+1])
			if len(cur) > 0 && (prevLower || (unicode.IsUpper(rs[i-1]) && nextLower)) {
				flush()
			}
			cur = append(cur, r)
		default:
			cur = append(cur, r)
		}
	}
	flush()
	return out
}

func goName(s string, useInit bool) string {
	var b strings.Builder
	for _, w := range words(s) {
		lw := strings.ToLower(w)
		if up, ok := initialisms[lw]; ok && useInit {
			b.WriteString(up)
			continue
		}
		b.WriteString(strings.ToUpper(lw[:1]) + lw[1:])
	}
	n := b.String()
	if n == "" || unicode.IsDigit(rune(n[0])) {
		n = "X" + n
	}
	return n
}

func sanitize(s string) string {
	r := strings.NewReplacer("\u2014", "-", "\u2013", "-", "\u201c", `"`, "\u201d", `"`, "\u2018", "'", "\u2019", "'", "\u2026", "...", "\u00a0", " ")
	s = r.Replace(s)
	var b strings.Builder
	for _, c := range s {
		if c < 128 {
			b.WriteRune(c)
		}
	}
	return b.String()
}

// doc returns a one-line doc comment body for a description.
func doc(desc any) string {
	s, _ := desc.(string)
	s = sanitize(s)
	if i := strings.Index(s, "\n\n"); i >= 0 {
		s = s[:i]
	}
	s = strings.Join(strings.Fields(s), " ")
	if len(s) > 220 {
		cut := s[:220]
		if i := strings.LastIndex(cut, ". "); i > 40 {
			cut = cut[:i+1]
		} else if i := strings.LastIndex(cut, " "); i > 0 {
			cut = cut[:i] + " ..."
		}
		s = cut
	}
	return s
}

func comment(indent, text string) string {
	if text == "" {
		return ""
	}
	return indent + "// " + text + "\n"
}

// ---------------------------------------------------------------- types

type typ struct {
	goType   string
	nullable bool
}

func (g *generator) refName(ref string) string { return ref[strings.LastIndex(ref, "/")+1:] }

func str(s obj, k string) string { v, _ := s[k].(string); return v }

func (g *generator) resolve(s obj, ctx string) typ {
	if ref, ok := s["$ref"].(string); ok {
		name := g.refName(ref)
		target := g.schemas[name].(obj)
		if _, isEnum := target["enum"]; isEnum {
			return typ{goType: name}
		}
		if isStruct(target) {
			return typ{goType: name}
		}
		return g.resolve(target, name)
	}
	for _, key := range []string{"anyOf", "oneOf"} {
		list, ok := s[key].([]any)
		if !ok {
			continue
		}
		var rest []obj
		nullable := false
		for _, v := range list {
			vo := v.(obj)
			if str(vo, "type") == "null" {
				nullable = true
				continue
			}
			rest = append(rest, vo)
		}
		if len(rest) == 1 {
			t := g.resolve(rest[0], ctx)
			t.nullable = t.nullable || nullable
			return t
		}
		if len(rest) == 2 {
			a, b := g.resolve(rest[0], ctx).goType, g.resolve(rest[1], ctx).goType
			if (a == "string" && b == "int") || (a == "int" && b == "string") {
				return typ{goType: "PathItem", nullable: nullable}
			}
		}
		allStrArrays, strs, strArrays := true, 0, 0
		for _, r := range rest {
			t := g.resolve(r, ctx)
			switch {
			case strings.HasPrefix(t.goType, "[]") && g.stringish(t.goType[2:]):
				strArrays++
			case g.stringish(t.goType):
				strs++
			default:
				allStrArrays = false
			}
		}
		if allStrArrays && strArrays >= 1 && strs == 1 {
			return typ{goType: "StringOrList", nullable: nullable}
		}
		if allStrArrays && strs == 0 && strArrays >= 1 {
			return typ{goType: "[]string", nullable: nullable}
		}
		g.warnings = append(g.warnings, "anyOf fallback to any at "+ctx)
		return typ{goType: "any", nullable: nullable}
	}
	if all, ok := s["allOf"].([]any); ok && len(all) == 1 {
		return g.resolve(all[0].(obj), ctx)
	}
	if _, ok := s["enum"]; ok {
		return typ{goType: "string"}
	}
	if _, ok := s["const"]; ok {
		return typ{goType: "string"}
	}
	switch str(s, "type") {
	case "string":
		if str(s, "format") == "date-time" {
			return typ{goType: "time.Time"}
		}
		return typ{goType: "string"}
	case "integer":
		return typ{goType: "int"}
	case "number":
		return typ{goType: "float64"}
	case "boolean":
		return typ{goType: "bool"}
	case "array":
		items, _ := s["items"].(obj)
		if items == nil {
			return typ{goType: "[]any"}
		}
		return typ{goType: "[]" + g.resolve(items, ctx+"Item").goType}
	case "object":
		if isStruct(s) {
			g.hoist(ctx, s)
			return typ{goType: ctx}
		}
		switch ap := s["additionalProperties"].(type) {
		case obj:
			if len(ap) == 0 {
				return typ{goType: "map[string]any"}
			}
			return typ{goType: "map[string]" + g.resolve(ap, ctx+"Value").goType}
		}
		return typ{goType: "map[string]any"}
	}
	return typ{goType: "any"}
}

func (g *generator) stringish(t string) bool {
	if t == "string" {
		return true
	}
	target, ok := g.schemas[t].(obj)
	if !ok {
		return false
	}
	_, isEnum := target["enum"]
	return isEnum
}

func (g *generator) hoist(name string, s obj) {
	if _, ok := g.hoisted[name]; ok {
		return
	}
	if _, ok := g.schemas[name]; ok {
		return
	}
	g.hoisted[name] = s
	g.hoistOrder = append(g.hoistOrder, name)
	g.structs[name] = true
}

func (g *generator) pointable(t string) bool {
	return g.scalars[t] || g.structs[t]
}

// ---------------------------------------------------------------- operations model

type param struct {
	name, in string
	required bool
	schema   obj
	desc     string
}

type operation struct {
	id, method, path, summary string
	service, goMethod         string
	params                    []param
	bodyRef                   string
	respRef                   string
	respStatus                string
	charged                   bool
}

func (g *generator) collectOps(paths obj) []operation {
	var ops []operation
	pk := make([]string, 0, len(paths))
	for p := range paths {
		pk = append(pk, p)
	}
	sort.Strings(pk)
	for _, p := range pk {
		item := paths[p].(obj)
		for _, m := range []string{"get", "post", "put", "patch", "delete"} {
			o, ok := item[m].(obj)
			if !ok {
				continue
			}
			op := operation{id: str(o, "operationId"), method: strings.ToUpper(m), path: p, summary: doc(o["summary"])}
			names, ok := opNames[op.id]
			if !ok {
				panic("no Go name for operation " + op.id)
			}
			op.service, op.goMethod = names[0], names[1]
			plist, _ := item["parameters"].([]any)
			plist = append(plist, asList(o["parameters"])...)
			for _, raw := range plist {
				po := raw.(obj)
				if str(po, "in") == "header" {
					if str(po, "name") == "Idempotency-Key" {
						op.charged = true
					}
					continue
				}
				req, _ := po["required"].(bool)
				sc, _ := po["schema"].(obj)
				op.params = append(op.params, param{name: str(po, "name"), in: str(po, "in"), required: req, schema: sc, desc: doc(po["description"])})
			}
			if rb, ok := o["requestBody"].(obj); ok {
				c, _ := rb["content"].(obj)
				if js, ok := c["application/json"].(obj); ok {
					if sc, ok := js["schema"].(obj); ok {
						op.bodyRef = g.refName(str(sc, "$ref"))
					}
				}
			}
			resp, _ := o["responses"].(obj)
			codes := make([]string, 0)
			for c := range resp {
				if strings.HasPrefix(c, "2") {
					codes = append(codes, c)
				}
			}
			sort.Strings(codes)
			if len(codes) > 0 {
				op.respStatus = codes[0]
				r := resp[codes[0]].(obj)
				if c, ok := r["content"].(obj); ok {
					if js, ok := c["application/json"].(obj); ok {
						if sc, ok := js["schema"].(obj); ok {
							op.respRef = g.refName(str(sc, "$ref"))
						}
					}
				}
			}
			ops = append(ops, op)
		}
	}
	sort.Slice(ops, func(i, j int) bool { return ops[i].id < ops[j].id })
	return ops
}

func asList(v any) []any { l, _ := v.([]any); return l }

// markRequestSchemas flags every schema reachable from a request body.
func (g *generator) markRequestSchemas(ops []operation) {
	var visit func(name string)
	var walk func(x any)
	walk = func(x any) {
		switch v := x.(type) {
		case obj:
			if ref, ok := v["$ref"].(string); ok {
				visit(g.refName(ref))
			}
			for _, c := range v {
				walk(c)
			}
		case []any:
			for _, c := range v {
				walk(c)
			}
		}
	}
	visit = func(name string) {
		if g.reqMode[name] {
			return
		}
		g.reqMode[name] = true
		walk(g.schemas[name])
	}
	for _, op := range ops {
		if op.bodyRef != "" {
			visit(op.bodyRef)
		}
	}
}

// ---------------------------------------------------------------- models

const header = "// Code generated by internal/gen from openapi/vaquill-us.json. DO NOT EDIT.\n\n"

func (g *generator) models() ([]byte, error) {
	var b bytes.Buffer
	b.WriteString(header)
	b.WriteString("package vaquill\n\nimport \"time\"\n\nvar _ = time.Time{}\n\n")
	names := make([]string, 0, len(g.schemas))
	for n := range g.schemas {
		names = append(names, n)
	}
	sort.Strings(names)
	var structBuf bytes.Buffer
	for _, n := range names {
		s := g.schemas[n].(obj)
		if err := g.emitSchema(&structBuf, n, s, g.reqMode[n]); err != nil {
			return nil, err
		}
	}
	// Hoisted inline objects may hoist further objects, so iterate by index.
	for i := 0; i < len(g.hoistOrder); i++ {
		n := g.hoistOrder[i]
		if err := g.emitSchema(&structBuf, n, g.hoisted[n].(obj), false); err != nil {
			return nil, err
		}
	}
	b.Write(structBuf.Bytes())
	return format.Source(b.Bytes())
}

func (g *generator) emitSchema(b *bytes.Buffer, name string, s obj, req bool) error {
	if enum, ok := s["enum"].([]any); ok {
		b.WriteString(comment("", name+" "+lowerFirst(doc(s["description"]))))
		fmt.Fprintf(b, "type %s string\n\nconst (\n", name)
		used := map[string]bool{}
		for _, e := range enum {
			v, _ := e.(string)
			cn := name + goName(v, true)
			for used[cn] {
				cn += "_"
			}
			used[cn] = true
			fmt.Fprintf(b, "\t%s %s = %q\n", cn, name, v)
		}
		b.WriteString(")\n\n")
		return nil
	}
	if !isStruct(s) {
		t := g.resolve(s, name)
		fmt.Fprintf(b, "// %s is a generated alias.\ntype %s = %s\n\n", name, name, t.goType)
		return nil
	}
	props := s["properties"].(obj)
	required := map[string]bool{}
	for _, r := range asList(s["required"]) {
		required[r.(string)] = true
	}
	keys := make([]string, 0, len(props))
	for k := range props {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	d := doc(s["description"])
	if d == "" {
		d = "is a generated model."
	} else {
		d = lowerFirst(d)
	}
	b.WriteString(comment("", name+" "+d))
	fmt.Fprintf(b, "type %s struct {\n", name)
	seen := map[string]bool{}
	for _, k := range keys {
		ps := props[k].(obj)
		t := g.resolve(ps, name+goName(k, false))
		_, hasDefault := ps["default"]
		fieldName := goName(k, true)
		if seen[fieldName] {
			fieldName = goName(k, false)
		}
		seen[fieldName] = true
		isReq := required[k] && !t.nullable
		value := isReq
		if !req && !t.nullable && hasDefault {
			value = true
		}
		goType := t.goType
		if !value && g.pointable(goType) {
			goType = "*" + goType
		}
		tag := k
		if !isReq || (!req && value) {
			tag += ",omitempty"
		}
		b.WriteString(comment("\t", doc(ps["description"])))
		fmt.Fprintf(b, "\t%s %s `json:\"%s\"`\n", fieldName, goType, tag)
	}
	b.WriteString("}\n\n")
	return nil
}

func lowerFirst(s string) string {
	if s == "" {
		return s
	}
	// Keep acronyms and identifiers intact.
	if len(s) > 1 && unicode.IsUpper(rune(s[1])) {
		return s
	}
	return strings.ToLower(s[:1]) + s[1:]
}

// ---------------------------------------------------------------- operations

func (g *generator) operations(ops []operation) ([]byte, error) {
	var b bytes.Buffer
	b.WriteString(header)
	b.WriteString("package vaquill\n\nimport (\n\t\"context\"\n\t\"time\"\n)\n\nvar _ = time.Time{}\n\n")
	// Query parameter structs first.
	for _, op := range ops {
		var optional []param
		for _, p := range op.params {
			if p.in == "query" && !p.required {
				optional = append(optional, p)
			}
		}
		if len(optional) == 0 {
			continue
		}
		name := goName(op.id, true) + "Params"
		b.WriteString(comment("", name+" are the optional query parameters of "+op.service+"."+op.goMethod+"."))
		fmt.Fprintf(&b, "type %s struct {\n", name)
		seen := map[string]bool{}
		for _, p := range optional {
			t := g.resolve(p.schema, name+goName(p.name, false))
			fn := goName(p.name, true)
			if seen[fn] {
				fn = goName(p.name, false)
			}
			seen[fn] = true
			gt := t.goType
			if g.pointable(gt) {
				gt = "*" + gt
			}
			b.WriteString(comment("\t", p.desc))
			fmt.Fprintf(&b, "\t%s %s `json:\"%s,omitempty\"`\n", fn, gt, p.name)
		}
		b.WriteString("}\n\n")
	}
	// Methods.
	for _, op := range ops {
		if err := g.emitMethod(&b, op); err != nil {
			return nil, err
		}
	}
	// Hoisted structs created while resolving parameters are emitted by models(),
	// which runs first, so nothing more is needed here.
	return format.Source(b.Bytes())
}

func lowerCamel(s string) string {
	ws := words(s)
	var b strings.Builder
	for i, w := range ws {
		lw := strings.ToLower(w)
		switch {
		case i == 0:
			b.WriteString(lw)
		case initialisms[lw] != "":
			b.WriteString(initialisms[lw])
		default:
			b.WriteString(strings.ToUpper(lw[:1]) + lw[1:])
		}
	}
	n := b.String()
	switch n {
	case "type", "func", "var", "range", "map", "package", "import", "select", "go", "default", "chan":
		n += "Arg"
	}
	return n
}

func (g *generator) emitMethod(b *bytes.Buffer, op operation) error {
	var args []string
	var pathKV, queryKV []string
	hasOptional := false
	for _, p := range op.params {
		t := g.resolve(p.schema, "arg")
		switch {
		case p.in == "path":
			an := lowerCamel(p.name)
			args = append(args, an+" "+t.goType)
			pathKV = append(pathKV, fmt.Sprintf("%q, %s", p.name, an))
		case p.in == "query" && p.required:
			an := lowerCamel(p.name)
			args = append(args, an+" "+t.goType)
			queryKV = append(queryKV, fmt.Sprintf("%q, %s", p.name, an))
		case p.in == "query":
			hasOptional = true
		}
	}
	paramsType := goName(op.id, true) + "Params"
	reqType := op.bodyRef
	if hasOptional {
		args = append(args, "params *"+paramsType)
	}
	if reqType != "" {
		args = append(args, "req *"+reqType)
	}
	argStr := "ctx context.Context"
	if len(args) > 0 {
		argStr += ", " + strings.Join(args, ", ")
	}
	argStr += ", opts ...CallOption"
	ret := "error"
	if op.respRef != "" {
		ret = "(*" + op.respRef + ", error)"
	}
	cost := "Free."
	if op.charged {
		cost = "Charged: sends an Idempotency-Key and counts toward WithMaxCredits."
	}
	b.WriteString(comment("", fmt.Sprintf("%s calls %s %s (operationId %s). %s", op.goMethod, op.method, op.path, op.id, cost)))
	if op.summary != "" {
		b.WriteString(comment("", op.summary))
	}
	recv := strings.ToLower(op.service[:1])
	fmt.Fprintf(b, "func (%s *%sService) %s(%s) %s {\n", recv, op.service, op.goMethod, argStr, ret)
	zero := "nil, "
	if op.respRef == "" {
		zero = ""
	}
	fail := "return " + zero + "err"
	fmt.Fprintf(b, "\tpath, err := pathf(%q", op.path)
	if len(pathKV) > 0 {
		b.WriteString(", " + strings.Join(pathKV, ", "))
	}
	b.WriteString(")\n\tif err != nil {\n\t\t" + fail + "\n\t}\n")
	q := "nil"
	if hasOptional || len(queryKV) > 0 {
		pa := "nil"
		if hasOptional {
			pa = "params"
		}
		fmt.Fprintf(b, "\tquery, err := buildQuery(%s", pa)
		if len(queryKV) > 0 {
			b.WriteString(", " + strings.Join(queryKV, ", "))
		}
		b.WriteString(")\n\tif err != nil {\n\t\t" + fail + "\n\t}\n")
		q = "query"
	}
	body := "nil"
	if reqType != "" {
		fmt.Fprintf(b, "\tif req == nil {\n\t\t%s\n\t}\n", "return "+zero+"errNilRequest(\""+reqType+"\")")
		body = "req"
	}
	reqLit := fmt.Sprintf("request{op: %q, method: %q, path: path, query: %s, body: %s, charged: %v}", op.id, op.method, q, body, op.charged)
	if op.respRef == "" {
		fmt.Fprintf(b, "\treturn %s.c.do(ctx, %s, nil, opts)\n}\n\n", recv, reqLit)
		return nil
	}
	fmt.Fprintf(b, "\tvar out %s\n\tif err := %s.c.do(ctx, %s, &out, opts); err != nil {\n\t\treturn nil, err\n\t}\n\treturn &out, nil\n}\n\n", op.respRef, recv, reqLit)
	return nil
}

// ---------------------------------------------------------------- meta

func (g *generator) meta(ops []operation) ([]byte, error) {
	var b bytes.Buffer
	b.WriteString(header)
	b.WriteString("package vaquill\n\n")
	b.WriteString("// Operations lists every operation of the frozen contract, sorted by operationId.\n")
	b.WriteString("var Operations = []OperationInfo{\n")
	for _, op := range ops {
		fmt.Fprintf(&b, "\t{ID: %q, Method: %q, Path: %q, Service: %q, GoMethod: %q, Charged: %v},\n",
			op.id, op.method, op.path, op.service, op.goMethod, op.charged)
	}
	b.WriteString("}\n")
	return format.Source(b.Bytes())
}
