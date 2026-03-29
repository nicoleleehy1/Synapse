declare module 'd3-force' {
  export function forceCollide<T>(radius?: number | ((node: T, i: number, nodes: T[]) => number)): {
    radius(): number | ((node: T, i: number, nodes: T[]) => number)
    radius(r: number | ((node: T, i: number, nodes: T[]) => number)): this
    strength(): number
    strength(s: number): this
    iterations(): number
    iterations(n: number): this
  }
}
