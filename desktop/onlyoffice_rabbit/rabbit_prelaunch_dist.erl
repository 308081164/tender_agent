-module(rabbit_prelaunch_dist).

-export([setup/1]).

%% Desktop OnlyOffice only needs the loopback AMQP listener.
%% A distributed Erlang node is not required for that listener, and this
%% setup must still return ok when distribution cannot be opened.
setup(_Context) ->
    _ = refresh_credentials(),
    ok.

refresh_credentials() ->
    try
        ok = credentials_obfuscation:refresh_config(),
        Cookie = erlang:get_cookie(),
        Secret = unicode:characters_to_binary(atom_to_list(Cookie)),
        ok = credentials_obfuscation:set_secret(Secret),
        Fallback = application:get_env(
                     rabbit,
                     credentials_obfuscation_fallback_secret,
                     <<"nocookie">>),
        ok = credentials_obfuscation:set_fallback_secret(Fallback),
        ok
    catch
        _Class:_Reason ->
            ok
    end.
