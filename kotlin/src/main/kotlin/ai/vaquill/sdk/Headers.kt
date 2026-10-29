package ai.vaquill.sdk

import java.util.TreeMap

/** Immutable, case-insensitive HTTP headers. A header may carry several values. */
public class Headers private constructor(private val map: TreeMap<String, List<String>>) {
    /** First value of [name], or null. */
    public operator fun get(name: String): String? = map[name]?.firstOrNull()

    /** All values of [name] (empty when absent). */
    public fun getAll(name: String): List<String> = map[name] ?: emptyList()

    /** Header names in lowercase. */
    public val names: Set<String> get() = map.keys.toSet()

    public fun toMap(): Map<String, List<String>> = map.toMap()

    override fun toString(): String = map.toString()

    override fun equals(other: Any?): Boolean = other is Headers && other.map == map

    override fun hashCode(): Int = map.hashCode()

    public companion object {
        public val EMPTY: Headers = Headers(TreeMap(String.CASE_INSENSITIVE_ORDER))

        /** Build from a name to values map (names are matched case-insensitively). */
        public fun of(source: Map<String, List<String>>): Headers {
            val tree = TreeMap<String, List<String>>(String.CASE_INSENSITIVE_ORDER)
            for ((k, v) in source) {
                if (k.isEmpty()) continue // the JDK reports the status line under an empty name
                val key = k.lowercase()
                tree[key] = (tree[key] ?: emptyList()) + v
            }
            return Headers(tree)
        }

        /** Build from single-valued pairs. */
        public fun of(vararg pairs: Pair<String, String>): Headers =
            of(pairs.groupBy({ it.first }, { it.second }))
    }
}
