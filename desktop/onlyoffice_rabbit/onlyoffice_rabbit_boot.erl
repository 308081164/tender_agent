-module(onlyoffice_rabbit_boot).

-export([start/0, start/1]).

%% Pin the local-broker shim, then boot RabbitMQ.
%% `-s Mod Func` is arity 0; some Erlang versions pass a list instead.
start() ->
    boot().

start(_Args) ->
    boot().

boot() ->
    Dir = filename:dirname(code:which(?MODULE)),
    true = code:add_patha(Dir),
    unload_stock_shim(),
    Beam = filename:join(Dir, "rabbit_prelaunch_dist"),
    {module, rabbit_prelaunch_dist} = code:load_abs(Beam),
    true = code:stick_mod(rabbit_prelaunch_dist),
    io:format("onlyoffice rabbit: local broker, distribution not required~n", []),
    rabbit:boot().

unload_stock_shim() ->
    case code:is_loaded(rabbit_prelaunch_dist) of
        false ->
            ok;
        {file, _} ->
            _ = code:unstick_mod(rabbit_prelaunch_dist),
            _ = code:purge(rabbit_prelaunch_dist),
            _ = code:delete(rabbit_prelaunch_dist),
            ok
    end.
