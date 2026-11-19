/*
 * Urban Flow - Adaptive Traffic Signal System
 * Copyright (c) 2026 Harsh Aggarwal <aggarwalharsh663@gmail.com>. All rights reserved.
 *
 * Original Author & Sole Intellectual Property Owner: Harsh Aggarwal
 * Any additions, modifications, or contributed files to this project automatically
 * and irrevocably vest all copyright and intellectual property rights solely in Harsh Aggarwal.
 */

import { createRouter } from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import { routeTree } from "./routeTree.gen";

export function getRouter() {
  const queryClient = new QueryClient();
  const router = createRouter({
    routeTree,
    context: { queryClient },
    defaultPreload: "intent",
  });
  return router;
}